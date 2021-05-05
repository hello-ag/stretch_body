from __future__ import print_function
import threading
import time
import signal
import logging
import os
import importlib
import copy

from stretch_body.device import Device
import stretch_body.base as base
import stretch_body.arm as arm
import stretch_body.lift as lift
import stretch_body.pimu as pimu
import stretch_body.head as head
import stretch_body.wacc as wacc
import stretch_body.end_of_arm as end_of_arm
import stretch_body.hello_utils as hello_utils

from serial import SerialException

from stretch_body.robot_monitor import RobotMonitor
from stretch_body.robot_sentry import RobotSentry
from stretch_body.robot_timestamp_manager import RobotTimestampManager
# #############################################################
class RobotDynamixelThread(threading.Thread):
    """
    This thread polls the status data of the Dynamixel devices
    at 15Hz
    """
    def __init__(self,robot):
        threading.Thread.__init__(self)
        self.robot=robot
        self.robot_update_rate_hz = 60.0  #Hz
        self.trajectory_downrate_int = 1  # Step the trajectory manager at 60hz for smooth vel ctrl
        self.status_downrate_int = 4  # Step the status at 15hz (most bus can handle)
        self.timer_stats = hello_utils.TimerStats()
        self.shutdown_flag = threading.Event()
        self.first_status=False
        self.titr = 0

    def run(self):
        while not self.shutdown_flag.is_set():
            ts = time.time()

            if (self.titr % self.trajectory_downrate_int) == 0:
                self.robot._push_dynamixel_waypoint_trajectory()

            if (self.titr % self.status_downrate_int) == 0:
                self.robot._pull_status_dynamixel()
            self.first_status=True

            self.titr = self.titr + 1
            te = time.time()
            tsleep = max(0.001, (1 / self.robot_update_rate_hz) - (te - ts))
            if not self.shutdown_flag.is_set():
                time.sleep(tsleep)

class RobotThread(threading.Thread):
    """
    This thread runs at 25Hz.
    It updates the status data of the Devices.
    It also steps the Sentry, TimeManager, and Monitor functions
    """
    def __init__(self,robot):
        threading.Thread.__init__(self)
        self.robot=robot

        self.robot_update_rate_hz = 25.0  #Hz
        self.monitor_downrate_int = 5  # Step the monitor at every Nth iteration
        self.sentry_downrate_int = 2  # Step the sentry at every Nth iteration
        self.trajectory_downrate_int = 5 #Step the trajectory manager every Nth iteration
        self.status_downrate_int = 1  # Step the status manager every iteration

        if self.robot.params['use_monitor']:
            self.robot.monitor.startup()
        if self.robot.params['use_sentry']:
            self.robot.sentry.startup()
        self.shutdown_flag = threading.Event()
        self.timer_stats = hello_utils.TimerStats()
        self.titr=0
        self.first_status = False

    def run(self):
        while not self.shutdown_flag.is_set():
            ts = time.time()
            if (self.titr % self.status_downrate_int) == 0:
                self.robot._pull_status_non_dynamixel()

            if (self.titr % self.trajectory_downrate_int) == 0:
                self.robot._push_non_dynamixel_waypoint_trajectory()
            self.first_status = True
            if self.robot.params['use_monitor']:
                if (self.titr % self.monitor_downrate_int) == 0:
                    self.robot.monitor.step()

            if self.robot.params['use_sentry']:
                if (self.titr % self.sentry_downrate_int) == 0:
                    self.robot.sentry.step()

            self.titr=self.titr+1
            te = time.time()
            tsleep = max(0.001, (1 / self.robot_update_rate_hz) - (te - ts))
            #print('Max rate (hz) %f'%(1/(te-ts)))
            if not self.shutdown_flag.is_set():
                time.sleep(tsleep)


class Robot(Device):
    """
    API to the Stretch RE1 Robot
    """
    def __init__(self,verbose=False):
        Device.__init__(self,verbose)
        self.params=self.robot_params['robot']
        self.monitor = RobotMonitor(self,verbose=verbose)
        self.sentry = RobotSentry(self,verbose=verbose)
        self.timestamp_manager = RobotTimestampManager(self)
        self.dirty_push_command = False
        self.lock = threading.RLock() #Prevent status thread from triggering motor sync prematurely

        self.status = {'pimu': {}, 'base': {}, 'lift': {}, 'arm': {}, 'head': {}, 'wacc': {}, 'end_of_arm': {},
                       'timestamps':{'hw_sync':hello_utils.SystemTimestamp(),
                                     'pimu_imu':hello_utils.SystemTimestamp(),'lift_enc':hello_utils.SystemTimestamp(),'arm_enc':hello_utils.SystemTimestamp(),
                                     'right_wheel_enc':hello_utils.SystemTimestamp(),'left_wheel_enc':hello_utils.SystemTimestamp(),
                                     'wacc_acc':hello_utils.SystemTimestamp(),
                                     'dynamixel_wall_time':hello_utils.SystemTimestamp(),
                                     'non_dynamixel_wall_time':hello_utils.SystemTimestamp()}}

        self.pimu = pimu.Pimu(verbose=verbose)
        self.status['pimu'] = self.pimu.status

        self.base = base.Base(verbose=verbose)
        self.status['base'] = self.base.status

        self.lift = lift.Lift(verbose=verbose)
        self.status['lift'] = self.lift.status

        self.arm = arm.Arm(verbose=verbose)
        self.status['arm'] = self.arm.status

        self.head = head.Head(verbose=verbose)
        self.status['head'] = self.head.status

        if 'custom_wacc' in self.params:
            module_name = self.params['custom_wacc']['py_module_name']
            class_name = self.params['custom_wacc']['py_class_name']
            self.wacc=getattr(importlib.import_module(module_name), class_name)(self)
        else:
            self.wacc=wacc.Wacc(verbose=verbose)
        self.status['wacc']=self.wacc.status

        self.end_of_arm=end_of_arm.EndOfArm(verbose=verbose)
        self.status['end_of_arm']=self.end_of_arm.status

        self.n_status_history = 25  # Store last 25 status (approx 1 second of data)
        self.status_id = 0
        self.status_history = [[self.status_id ,copy.deepcopy(self.status)]]

        self.devices={ 'pimu':self.pimu, 'base':self.base, 'lift':self.lift, 'arm': self.arm, 'head': self.head, 'wacc':self.wacc, 'end_of_arm':self.end_of_arm}
        self.rt=None
        self.dt=None


    # ############ Status Management ####################
    def update_status_history(self,dynamixel=False,non_dynamixel=False):
        #Because the dynamixel and non_dynamixel status data is updated at different rates
        #from different threads we build a composite version here using the most recent data of
        #on and the stale data of the other.
        s_new=None
        if dynamixel:
            #Get the stale non_dynamixel status and copy in the new dynamixel data
            s_new = self.get_status()
            s_new['timestamps']['dynamixel_wall_time'] = hello_utils.SystemTimestamp().from_wall_time()
            if self.end_of_arm:
                s_new['end_of_arm']=copy.deepcopy(self.end_of_arm.status)
            if self.head:
                s_new['head'] = copy.deepcopy(self.head.status)
        if non_dynamixel:
            self.timestamp_manager.step() # This will compute the timestamps ond update the status message
            s_new=copy.deepcopy(self.status)

        # Record the new status
        if s_new is not None:
            self.status_id = self.status_id + 1
            self.status_history.append([self.status_id, s_new])

        if len(self.status_history) == self.n_status_history: #Ring buffer
            self.status_history = self.status_history[1:]

    def __get_status_from_id(self,id):
        id_last=self.status_history[-1][0]
        idx = id-id_last - 1
        if idx>-1 or idx<-1*len(self.status_history):
            return None
        return self.status_history[idx][1]


    def get_status(self):
        """
        Thread safe and atomic read of current Robot status data
        Returns as a dict.
        """
        with self.lock:
            return copy.deepcopy(self.status_history[-1][1])

    # ###########  Device Methods #############
    def startup(self):
        """
        To be called once after class instantiation.
        Prepares devices for communications and motion
        """

        # Set up logging
        t = time.localtime()
        capture_date = str(t.tm_year) + str(t.tm_mon).zfill(2) + str(t.tm_mday).zfill(2) + str(t.tm_hour).zfill(
            2) + str(t.tm_min).zfill(2)
        self.log_filename = os.environ['HELLO_FLEET_PATH'] + '/log/' + self.params[
            'serial_no'] + '_monitor_' + capture_date + '.log'
        self.logger = logging.getLogger('robot')
        self.logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler(self.log_filename)
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - ' + hello_utils.get_fleet_id() + ' - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        if self.params['log_to_console']:
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)

        self.logger.info('Starting up Robot')
        for k in self.devices.keys():
            if self.devices[k] is not None:
                if not self.devices[k].startup():
                    pass
                #    print('Startup failure on %s. Exiting.'%k)
                #    exit()

        self.timestamp_manager.startup()
        if self.params['sync_mode_enabled']:
            self.enable_sync_mode()
        else:
            self.disable_sync_mode()

        # Register the signal handlers
        signal.signal(signal.SIGTERM, hello_utils.thread_service_shutdown)
        signal.signal(signal.SIGINT, hello_utils.thread_service_shutdown)
        self.rt = RobotThread(self)
        self.rt.setDaemon(True)
        self.rt.start()
        self.dt = RobotDynamixelThread(self)
        self.dt.setDaemon(True)
        self.dt.start()
        #Wait for threads to start reading data
        ts=time.time()
        while not self.rt.first_status and not self.dt.first_status and time.time()-ts<3.0:
            time.sleep(0.1)
        #if not self.rt.first_status  or not self.dt.first_status :
        #    self.logger.warning('Failed to startup up robot threads')

    def stop(self):
        """
        To be called once before exiting a program
        Cleanly stops down motion and communication
        """
        print('Shutting down robot...')
        if self.rt is not None:
            self.rt.shutdown_flag.set()
            self.rt.join()
        if self.dt is not None:
            self.dt.shutdown_flag.set()
            self.dt.join()
        for k in self.devices.keys():
            if self.devices[k] is not None:
                print('Shutting down',k)
                self.devices[k].stop()


    def enable_sync_mode(self):
        self.arm.motor.enable_sync_mode()
        self.arm.push_command()

        self.lift.motor.enable_sync_mode()
        self.lift.push_command()

        self.base.left_wheel.enable_sync_mode()
        self.base.right_wheel.enable_sync_mode()
        self.base.push_command()

        self.wacc.enable_sync_mode()
        self.wacc.push_command()

        self.pimu.enable_sync_mode()
        self.pimu.push_command()

    def disable_sync_mode(self):
        self.pimu.disable_sync_mode()
        self.pimu.push_command()

        self.arm.motor.disable_sync_mode()
        self.arm.push_command()

        self.lift.motor.disable_sync_mode()
        self.lift.push_command()

        self.base.left_wheel.disable_sync_mode()
        self.base.right_wheel.disable_sync_mode()
        self.base.push_command()

        self.wacc.disable_sync_mode()
        self.wacc.push_command()


    def pretty_print(self):
        s=self.get_status()
        print('##################### HELLO ROBOT ##################### ')
        print('Time',time.time())
        print('Serial No',self.params['serial_no'])
        print('Batch', self.params['batch_name'])
        self._pretty_print_dict('Status',s)

    def push_command(self):
        """
        Cause all queued up RPC commands to be sent down to Devices
        """
        with self.lock:
            self.base.push_command()
            self.arm.push_command()
            self.lift.push_command()
            self.pimu.push_command()
            self.wacc.push_command()
            self.pimu.trigger_motor_sync()

# ##################Home and Stow #######################################

    def is_calibrated(self):
        """
        Returns true if homing-calibration has been run all joints that require it
        """
        ready = self.lift.motor.status['pos_calibrated']
        ready = ready and self.arm.motor.status['pos_calibrated']
        for j in self.end_of_arm.joints:
            req = self.end_of_arm.motors[j].params['req_calibration'] and not self.end_of_arm.motors[j].is_calibrated
            ready = ready and not req
        return ready

    def stow(self):
        """
        Cause the robot to move to its stow position
        Blocking.
        """
        self.head.move_to('head_pan', self.params['stow']['head_pan'])
        self.head.move_to('head_tilt',self.params['stow']['head_tilt'])

        lift_stowed=False
        if self.lift.status['pos']<=self.params['stow']['lift']: #Needs to come up before bring in arm
            print('--------- Stowing Lift ----')
            self.lift.move_to(self.params['stow']['lift'])
            self.push_command()
            time.sleep(0.25)
            ts = time.time()
            while not self.lift.motor.status['near_pos_setpoint'] and time.time() - ts < 3.0:
                time.sleep(0.1)
            lift_stowed=True

        #Bring in arm before bring down
        print('--------- Stowing Arm ----')
        self.arm.move_to(self.params['stow']['arm'])
        self.push_command()
        time.sleep(0.25)
        ts = time.time()
        while not self.arm.motor.status['near_pos_setpoint'] and time.time() - ts < 3.0:
            time.sleep(0.1)

        # Fold in wrist and gripper
        print('--------- Stowing Wrist Yaw ----')
        self.end_of_arm.move_to('wrist_yaw', self.params['stow']['wrist_yaw'])
        if self.end_of_arm.is_tool_present('StretchGripper'):
            self.end_of_arm.move_to('stretch_gripper', self.params['stow']['stretch_gripper'])
        time.sleep(0.25)


        #Now bring lift down
        if not lift_stowed:
            print('--------- Stowing Lift ----')
            self.lift.move_to(self.params['stow']['lift'])
            self.push_command()
            time.sleep(0.25)
            ts = time.time()
            while not self.lift.motor.status['near_pos_setpoint'] and time.time() - ts < 10.0:
                time.sleep(0.1)

        #Make sure wrist yaw is done before exiting
        while self.end_of_arm.motors['wrist_yaw'].motor.is_moving():
            time.sleep(0.1)

    def home(self):
        """
        Cause the robot to home its joints by moving to hardstops
        Blocking.
        """
        #Turn off so homing can happen w/o Pimu
        psm=self.pimu.config['sync_mode_enabled']
        self.pimu.disable_sync_mode()
        self.push_command()

        if self.head is not None:
            print('--------- Homing Head ----')
            self.head.home()

        # Home the lift
        if self.lift is not None:
            print('--------- Homing Lift ----')
            self.lift.home()

        # Home the arm
        if self.arm is not None:
            print('--------- Homing Arm ----')
            self.arm.home()

        # Home the end-of-arm
        if self.end_of_arm is not None:
            for j in self.end_of_arm.joints:
                print( '--------- Homing ', j, '----')
                self.end_of_arm.home(j)
        #Let user know it is done
        if psm:
            self.pimu.enable_sync_mode()
        self.pimu.trigger_beep()
        self.push_command()
    # ################ Helpers #################################

    def _pretty_print_dict(self, t, d):
        print('--------', t, '--------')
        for k in d.keys():
            if type(d[k]) != dict:
                print(k, ' : ', d[k])
        for k in d.keys():
            if type(d[k]) == dict:
                self._pretty_print_dict(k, d[k])

    def _pull_status_dynamixel(self):
        try:
            self.end_of_arm.pull_status()
            self.head.pull_status()
            self.update_status_history(dynamixel=True)
        except SerialException:
            print('Serial Exception on Robot Step_Dynamixel')

    def _pull_status_non_dynamixel(self):
        #Send a status sync message to all slaves, so timestamped at same time
        if self.params['sync_mode_enabled']:
            self.pimu.trigger_status_sync()
            self.wacc.trigger_status_sync()
        self.wacc.pull_status()
        self.base.pull_status()
        self.lift.pull_status()
        self.arm.pull_status()
        self.pimu.pull_status()
        self.update_status_history(non_dynamixel=True) #Updates timestamps

    def _push_non_dynamixel_waypoint_trajectory(self):
        if self.arm.motor.status['trajectory_active']:
            self.arm.push_trajectory()

        if self.lift.motor.status['trajectory_active']:
            self.lift.push_trajectory()

        if self.base.left_wheel.status['trajectory_active'] or \
           self.base.right_wheel.status['trajectory_active']:
            self.base.push_trajectory()

    def _push_dynamixel_waypoint_trajectory(self):
        if self.head.get_joint('head_pan').status['trajectory_active']:
            self.head.get_joint('head_pan').push_trajectory()

        if self.head.get_joint('head_tilt').status['trajectory_active']:
            self.head.get_joint('head_tilt').push_trajectory()

        if self.end_of_arm.motors['wrist_yaw'].status['trajectory_active']:
            self.end_of_arm.motors['wrist_yaw'].push_trajectory()

    def is_trajectory_executing(self):
        # Executing is defined as the joint controller is tracking the trajectory
        # Returns false after the last segment has finished executing on the joint controller
        return self.arm.motor.status['trajectory_active'] or  self.lift.motor.status['trajectory_active'] \
                or self.base.left_wheel.status['trajectory_active'] or self.base.right_wheel.status['trajectory_active'] \
                or self.head.motors['head_pan'].status['trajectory_active'] or self.head.motors['head_tilt'].status['trajectory_active'] \
                or self.end_of_arm.motors['wrist_yaw'].status['trajectory_active']

    def start_trajectory(self):
        """Coordinated multi-joint trajectory following.
        """
        self.lift.start_trajectory(threaded=False)
        self.arm.start_trajectory(threaded=False)
        self.base.start_trajectory(threaded=False)

        if self.params['sync_mode_enabled']:
            self.pimu.trigger_motor_sync() #Start motion of non-dynamixel joints

        self.head.get_joint('head_pan').start_trajectory(position_ctrl=False, threaded=False, watchdog_timeout=0)
        self.head.get_joint('head_tilt').start_trajectory(position_ctrl=False, threaded=False, watchdog_timeout=0)
        self.end_of_arm.motors['wrist_yaw'].start_trajectory(position_ctrl=True, threaded=False)
        time.sleep(0.1) #Give time for synced trajectories to start

    def stop_trajectory(self):
        """Halt executing trajectory
        """
        self.lift.stop_trajectory()
        self.arm.stop_trajectory()
        self.base.stop_trajectory()
        self.head.get_joint('head_pan').stop_trajectory()
        self.head.get_joint('head_tilt').stop_trajectory()
        self.end_of_arm.motors['wrist_yaw'].stop_trajectory()