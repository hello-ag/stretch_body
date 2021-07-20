import setuptools
from stretch_body.version import __version__

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="hello_robot_stretch_body",
    version=__version__,
    author="Hello Robot Inc.",
    author_email="support@hello-robot.com",
    description="Stretch RE1 low level Python API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/hello-robot/stretch_body",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 2",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)"
    ],
    install_requires=['numpy', 'scipy', 'matplotlib', 'ipython', 'jupyter', 'pandas', 'sympy', 'nose', 'PyYaml',
                      'inputs', 'drawnow', 'rplidar-roboticia', 'snakeviz', 'pyusb', 'SpeechRecognition', 'pixel-ring',
                      'click', 'cma', 'opencv-contrib-python', 'colorama', 'numba',
                      'scikit-image', 'open3d', 'pyrealsense2', 'pathlib', 'psutil',
                      'jsonschema>=2.6.0', 'qtconsole>=4.7.7', 'llvmlite == 0.31.0; python_version < "3.0"',
                      'gitpython', 'urdfpy', 'dynamixel-sdk >= 3.1; python_version >= "3.2.0"', 'pyyaml>=5.1',
                      'hello-robot-stretch-factory', 'hello-robot-stretch-tool-share']
)
