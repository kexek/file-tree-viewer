
from setuptools import setup, find_packages

setup(
    name="file-tree-viewer",
    version="0.1.0",
    description="A graphical utility for viewing and exporting file trees with content",
    author="Your Name",
    author_email="your.email@example.com",
    packages=find_packages(),
    py_modules=["file_tree_viewer"],
    install_requires=[
        # No external dependencies - using only standard library
    ],
    entry_points={
        'console_scripts': [
            'file-tree-viewer=file_tree_viewer:main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)