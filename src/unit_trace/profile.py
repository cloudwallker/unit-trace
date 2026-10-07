"""Report the actual installed scalar engine and bundled definitions."""

import hashlib
from importlib import metadata, resources
import platform

from .models import Profile


def get_profile() -> Profile:
    dependencies = {name: metadata.version(name) for name in
                    ('Pint', 'flexcache', 'flexparser', 'platformdirs', 'typing_extensions')}
    hashes = {f'pint/{name}': hashlib.sha256(resources.files('pint').joinpath(name).read_bytes()).hexdigest()
              for name in ('default_en.txt', 'constants_en.txt')}
    return Profile('unit-trace-scalar-v1', 1, platform.python_version(), dependencies['Pint'],
                   dependencies, 1, hashes)
