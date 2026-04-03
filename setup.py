from setuptools import setup, find_packages

setup(
    name='api-assertion-guard',
    version='0.1.0',
    description='API 自动化测试断言质量检查工具',
    author='lizhangcheng',
    author_email='748961219@qq.com',
    packages=find_packages(),
    python_requires='>=3.8',
    install_requires=[
        'ruamel.yaml>=0.18.0',
        'rich>=13.0.0',
    ],
    entry_points={
        'console_scripts': [
            'aag=aag_cli:main',
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
