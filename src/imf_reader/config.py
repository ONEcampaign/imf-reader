"""Configuration for the IMF reader."""


class NoDataError(Exception):
    """This is a custom exception that is raised when no UIS data exists"""

    pass


class UnexpectedFileError(Exception):
    """This is a custom exception that is raised when an unexpected file is found in the zip folder
    or if there is an issue with the file structure"""

    pass