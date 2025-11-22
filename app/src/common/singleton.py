"""
Singleton Pattern Implementation

This module provides a metaclass implementation of the Singleton design pattern,
ensuring that only one instance of a class can be created.
"""

# First, let's create a base singleton class


class SingletonMeta(type):
    """
    Metaclass for implementing the Singleton pattern.
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
