'''This is a temporary test file to check the capapbility of testing for new upcoming PRs'''


'''Currently, to make things easier the test file will do two things - 
1. run the robot home and stow scripts to ensure that the robot is moving, 
2. read some data from the docs file to check that the data from new PR is accessible
'''
import unittest
import time
from os import listdir
import stretch_body.robot
class Temporary_tests(unittest.TestCase):

	r = stretch_body.robot.Robot()
	r.startup()
	print("Starting home and stow operations")
	r.home()
	# r.pull_status()
	# time.sleep(1) # wrist_yaw yields 3.4 (stowed position) unless sleep here
	# self.assertAlmostEqual(r.status['lift']['pos'], 0.58, places=1)
	# self.assertAlmostEqual(r.status['arm']['pos'], 0.1, places=3)
	# self.assertAlmostEqual(r.status['head']['head_tilt']['pos'], 0.0, places=1)
	# self.assertAlmostEqual(r.status['head']['head_pan']['pos'], 0.0, places=1)
	# self.assertAlmostEqual(r.status['end_of_arm']['wrist_yaw']['pos'], 0.0, places=1)
	# self.assertAlmostEqual(r.status['end_of_arm']['stretch_gripper']['pos'], 0.0, places=1)

	# r.stow()
	# r.pull_status()
	# self.assertAlmostEqual(r.status['lift']['pos'], 0.2, places=1)
	# self.assertAlmostEqual(r.status['arm']['pos'], 0.0, places=3)
	# self.assertAlmostEqual(r.status['head']['head_tilt']['pos'], 0.0, places=1)
	# self.assertAlmostEqual(r.status['head']['head_pan']['pos'], 0.0, places=1)
	# self.assertAlmostEqual(r.status['end_of_arm']['wrist_yaw']['pos'], 3.4, places=1)
	# self.assertAlmostEqual(r.status['end_of_arm']['stretch_gripper']['pos'], 0.0, places=1)

	r.stop()

	# print("stowing done")
	path = "/docs/git_action_files/"

	files = listdir(path)
	print(files)
	for f in files:
		text_file = open(path+f,"r")
		data = text_file.read()
		print(data)