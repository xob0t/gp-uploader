from setuptools import find_packages, setup

setup(
    name='gp-uploader',
    version='0.4.12',
    description='Script to monitor a directory and upload any existing files to google photo using adb connected android device',
    author='xob0t',
    url='https://github.com/xob0t/gp-uploader',
    packages=find_packages(),
    install_requires=[
        'rich',
        'lxml',
    ],
    entry_points={
        'console_scripts': ['gp-uploader = gp_uploader.watch_dir:main']
    },
)