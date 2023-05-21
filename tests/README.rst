Run all tests via `make test` in the top most project directory.


Integration tests
=================

The most important integration tests are in the main user documentation. Here
we only include cases that are not useful there.

.. code::

    $ grocy_importer.py --help
    usage: grocy_importer.py [-h] [--timeout N] [--dry-run]
                             {whereis,shopping-list,recipe,purchase,chore,userfield}
                             ...
    
    Help importing into Grocy
    
    positional arguments:
      {whereis,shopping-list,recipe,purchase,chore,userfield}
        whereis             show location of a product
        shopping-list       export shopping list in todo.txt format
        recipe              assist importing recipes from the web
        purchase            import purchases
        chore               Prompt to do each overdue chore
        userfield           Quickly add userfields
    
    options:
      -h, --help            show this help message and exit
      --timeout N           Override the default timeout for each REST call
      --dry-run             perform a trial run with no changes made


Error messages
--------------

Should show a nice error message when it can't connect to the server:

.. code::

    $ GROCY_BASE_URL='http://example.com/' GROCY_API_KEY='abc' grocy_importer.py chore show
    Error: Connection to Grocy failed: Not Found


Recipe
------

.. code::

    $ grocy_importer.py recipe --help
    usage: grocy_importer.py recipe [-h] url
    
    Check if ingredients and their units are known to grocy for a recipe to be
    imported
    
    positional arguments:
      url
    
    options:
      -h, --help  show this help message and exit

.. code::

    $ grocy_importer.py recipe https://cookidoo.de/recipes/recipe/de-DE/r94080
    Unknown ingredients:
    Ingredient(amount='4', unit='dessert', name='apples', full='4 dessert apples')
    Ingredient(amount='½', unit='-', name='1 tsp ground cinnamon', full='½ - 1 tsp ground cinnamon')
    Ingredient(amount='1', unit='pinch', name='ground nutmeg', full='1 pinch ground nutmeg')
    Ingredient(amount='80', unit='g', name='rolled oats', full='80 g rolled oats')
    Ingredient(amount='40', unit='g', name='blanched almonds', full='40 g blanched almonds')
    Ingredient(amount='200', unit='g', name='ice cubes', full='200 g ice cubes')
    
    Unknown units:
    Ingredient(amount='800', unit='g', name='milk', full='800 g milk')
    
    Unknown unit convertion:
    

Userfields
----------

.. code::

    $ grocy_importer.py userfield --help
    usage: grocy_importer.py userfield [-h] entity file
    
    Add userfield(s) to (usally) many grocy entities from a yaml file.
    
    positional arguments:
      entity      the type of entity that the user fields should be added to. E.g.
                  batteries, chores, chores_log, ...
      file        a yaml file with the user fields to set
    
    options:
      -h, --help  show this help message and exit

.. code::

    $ cat tests/userfields.yml
    ---
    - id: 1
      customfield1: Changed entity1, field 1
    - id: 2
      customfield1: Changed entity2, field 2
      customfield2: Changed entity2, field 2

In addition to the user fields that should be set only the id of the entity for the fields needs to be specified.

.. code::

    $ grocy_importer.py userfield userentity-exampleuserentity tests/userfields.yml
    userentity-exampleuserentity 1
    userentity-exampleuserentity 2

In case the userfields doesn't match the entity an error will be printed:

.. code::

    $ grocy_importer.py userfield chores tests/userfields.yml
    Error: Connection to Grocy failed with Bad Request: Field customfield1 is not a valid userfield of the given entity

In case the entity id doesn't exist, we would hope that grocy would complain with an error. Instead it just saves the userfields.

.. code::

    $ grocy_importer.py userfield userentity-exampleuserentity tests/userfields-missing-entity.yml
    userentity-exampleuserentity 10001
    userentity-exampleuserentity 2

In case the given file isn't a yml an error will be printed:

.. code::

    $ grocy_importer.py userfield userentity-exampleuserentity tests/README.rst
    Error: yaml invalid.

In case the id of an item is missing an error will be printed:

.. code::

    $ grocy_importer.py userfield userentity-exampleuserentity tests/userfields-missing-id.yml
    Error: missing id-field for entity in yaml file.
    userentity-exampleuserentity 2

In case the given list is empty

.. code::

    $ grocy_importer.py userfield userentity-exampleuserentity /dev/null
    Error: list missing in yaml file.

