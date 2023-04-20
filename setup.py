from setuptools import setup

setup(name='grocy_importer',
      version='0.1',
      description='Help importing into and from Grocy',
      url='https://gitlab.com/adaschma/grocy-importer',
      author='Adam Schmalhofer',
      author_email='code@adaschma.name',
      license='MIT',
      packages=[],
      zip_safe=False,
      scripts=['grocy_importer.py'],
      install_requires=[
            'bs4',
            'requests',
            'marshmallow',
            'appdirs',
            'argcomplete',
            'pdfminer.six',
            'html5lib',
            'yaml',
          ])
