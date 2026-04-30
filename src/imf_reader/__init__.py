# read version from installed package
from importlib.metadata import version

__version__ = version("imf_reader")

from imf_reader import cache as cache  # noqa: F401
