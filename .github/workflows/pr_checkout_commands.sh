while getopts n:b: flag
do
    case "${flag}" in
        n) pr_number=${OPTARG};;
        b) branch_name=${OPTARG};;
    esac
done
cd repos
git clone https://github.com/hello-ag/stretch_body.git stretch_body_PR_testing
cd stretch_body_PR_testing
git fetch origin pull/$pr_number/head:$branch_name
git checkout $branch_name
cd body
declare -a TestFiles=("test_arm" "test_dxl_comms" "test_end_of_arm" "test_hello_utils" "test_robot_params" "test_timing_stats" "test_base" "test_dynamixel_hello_XL430" "test_end_of_arm_tools" "test_lift" "test_robot" "test_timing_stats" "test_arm" "test_device" "test_dynamixel_XL430" "test_hello_utils" "test_pimu" "test_steppers" )
declare -a TestFiles2=("test_hello_utils")
declare -a TestFiles3=("test_robot_params")
# Iterate the string array using for loop
for fileName in ${TestFiles3[@]}; do
   python -m unittest test.$fileName
done
cd ../..
rm -rf stretch_body_PR_testing
exit
~^Z