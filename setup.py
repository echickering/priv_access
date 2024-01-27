from setuptools import setup, find_packages

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
)
