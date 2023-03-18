==============
todo-txt chore
==============

I use `todo-txt`_ for my personal todo's and really love using it to decide
what to do next. There are some extensions that help with reaccuring tasks,
however Grocy_ has some unique advantages:

- easily coordinate chores with family members

- integrates_ with home automation system `home assistant`_ to track chores via
  `power usage`_ or `NFC scanning`_

- easy to use web interface to setup chores as well as an overview and journal
  for each of them.



.. _todo-txt: http://todotxt.org/

.. _Grocy: https://grocy.info/

.. _integrates: https://github.com/custom-components/grocy

.. _home assistant: https://www.home-assistant.io/

.. _power usage: https://community.home-assistant.io/t/notify-or-do-something-when-an-appliance-like-a-dishwasher-or-washing-machine-finishes/254841

.. _NFC scanning: https://www.home-assistant.io/integrations/tag/


Installation
============

Clone this repository and create a link `$TODO_ACTIONS_DIR/chore` to
`grocy_importer.py`. Besides `todo-txt` itself only `python3`_ and some python libraries are required.
Those are listed in requirements.txt and can be installed via `pip`_:

.. code:: sh

   $ pip install -r requirements.txt

If you are using `Debian GNU/LINUX`_ you can use the system package manager instead.

.. _python3: https://python.org/
.. _pip: https://pip.pypa.io/en/stable/getting-started/
.. _Debian GNU/Linux: https://www.debian.org/


Setup
=====

Copy config.ini to ~/.config/grocy-importer/config.ini and set the values to
match your setup. Especially grocy's base_url and api_key need to be set.

.. code:: ini

    #$ cat config.ini
    [grocy]
    
    base_url = http://localhost/grocy/public/api
    api_key = PLEASESET
    
    [netto]
    
    # Uncomment the following line to manually set the grocy shopping location to use.
    # This isn't needed if you only have one shopping location with a name starting with
    # 'netto' (case insensitive).
    
    #shopping_location_id = 42
    
    [rewe]
    
    # Uncomment the following line to manually set the grocy shopping location to use.
    # This isn't needed if you only have one shopping location with a name starting with
    # 'rewe' (case insensitive).
    
    #shopping_location_id = 7
    
    [dm]
    
    # Uncomment the following line to manually set the grocy shopping location to use.
    # This isn't needed if you only have one shopping location with a name starting with
    # 'dm' (case insensitive).
    
    #shopping_location_id = 14


Usage
=====

.. code:: sh

    $ todo-txt help chore
    usage: chore chore [-h] [--timeout N] [--dry-run] {ls,push,pull} ...
    
    positional arguments:
      {ls,push,pull}
        ls            List chores from grocy
        push          Send completed and rescheduled chores in todo.txt to grocy
        pull          Replace chores in todo.txt with current ones from grocy
    
    options:
      -h, --help      show this help message and exit
      --timeout N     Override the default timeout for each REST call
      --dry-run       perform a trial run with no changes made

    
Let's demonstrate how to use of `chore` on a short todo list:

.. code:: sh

    $ todo-txt ls
    1 Call Mom @Phone +Family
    2 Schedule annual checkup +Health
    3 Outilne chapter 5 +Novel @Computer
    4 Add cover sheets @Office +TPSReports
    5 Download Todo.txt mobile app @Phone
    6 Pick up milk @GroceryStore
    7 Plan backyard herb garden @Home
    --
    TODO: 7 of 7 tasks shown

First let's see what chores grocy has for us:

.. code:: sh
 
    $ todo-txt chore ls --all
    Change towels in the bathroom chore:1
    Mop the kitchen floor chore:2
    Take out the trash chore:3
    Vacuum the living room floor chore:4
    Clean the litter box chore:5
    Change the bed sheets chore:6

The --all option gets all chore including the ones that are not overdue or manually scheduled.

Now if we want to have these in our todo.txt we use the pull command:

.. code:: sh

    $ todo-txt chore pull --all
    $ todo-txt ls
    01 Call Mom @Phone +Family
    02 Schedule annual checkup +Health
    03 Outilne chapter 5 +Novel @Computer
    04 Add cover sheets @Office +TPSReports
    05 Download Todo.txt mobile app @Phone
    06 Pick up milk @GroceryStore
    07 Plan backyard herb garden @Home
    08 Change towels in the bathroom chore:1
    09 Mop the kitchen floor chore:2
    10 Take out the trash chore:3
    11 Vacuum the living room floor chore:4
    12 Clean the litter box chore:5
    13 Change the bed sheets chore:6
    --
    TODO: 13 of 13 tasks shown

We can now work with the todo list as we normally would and complete the tasks.
However we need to keep the completed tasks in todo.txt and only archive them
later.

.. code:: sh

    $ todo-txt -a do 8    #=> --exit 0
    $ todo-txt -a do 10   #=> --exit 0
    $ todo-txt -a do 11   #=> --exit 0
    $ todo-txt -a do 12   #=> --exit 0
    $ todo-txt -a do 13   #=> --exit 0

.. code:: sh

    $ todo-txt chore pull
    Warning: completed chore 1. Run "push" and "archive" first. Aborting.
    $ todo-txt chore push    #=> --lines 5
    $ todo-txt archive   #=> --exit 0
    $ todo-txt chore pull
    $ todo-txt ls
    1 Call Mom @Phone +Family
    2 Schedule annual checkup +Health
    3 Outilne chapter 5 +Novel @Computer
    4 Add cover sheets @Office +TPSReports
    5 Download Todo.txt mobile app @Phone
    6 Pick up milk @GroceryStore
    7 Plan backyard herb garden @Home
    8 Mop the kitchen floor chore:2
    --
    TODO: 8 of 8 tasks shown
