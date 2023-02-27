import re
from packaging.version import Version

output = ['grizzly-cli 3.0.11.dev24\n', '└── grizzly 2.5.11\n', '    └── locust <2.13,>=2.12.0\n']

print(''.join(output))

matches = re.match(r'.*grizzly ([0-9]+\.[0-9]+\.[0-9]+).*', output[1])
if matches:
    version = Version(matches.group(1))
    if version < Version('2.6.0'):
        print('special case needed')
    else:
        print('good to go!')
else:
    print(matches)
