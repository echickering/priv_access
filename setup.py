import os
import shutil
from setuptools import setup, find_packages
from setuptools.command.install import install

class CustomInstallCommand(install):
    """Customized setuptools install command to copy configuration files."""
    def run(self):
        install.run(self)
        config_files = [
            'config/aws_credentials.example.yml',
            'config/config.example.yml',
            'config/onprem_config.example.yml',
            'config/ec2_template.example.yml',
            'config/vpc_template.example.yml',
            'config/pan_credentials.example.yml',
        ]
        for file in config_files:
            if os.path.exists(file):
                destination = file.replace('.example', '')
                if not os.path.exists(destination):
                    print(f"Copying {file} to {destination}")
                    shutil.copy(file, destination)
                else:
                    print(f"{destination} already exists, skipping.")

setup(
    name='private-sase-project',
    version='0.1.0',
    description='A Python project to build a private SASE environment in AWS using Palo Alto NGFW',
    author='Eric Chickering',
    author_email='eric.chickering@gmail.com',
    packages=find_packages(),
    install_requires=[
        'boto3',
        'pyyaml',
        'requests',
    ],
    python_requires='>=3.6',
    cmdclass={
        'install': CustomInstallCommand,
    },
)
