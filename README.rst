==============
todo-txt chore
==============

I use `todo-txt`_ for my personal todo's and really love using it to decide
what to do next. There are some extensions that help with reoccurring tasks,
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

.. code::

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

Alternatively you can set the $GROCY_BASE_URL and $GROCY_API_KEY environment variables e.g.
in your todo.cfg.


Usage
=====

.. code::

    $ todo-txt help chore
    usage: chore chore [-h] [--timeout N] [--dry-run] {ls,push,pull,drop} ...
    
    positional arguments:
      {ls,push,pull,drop}
        ls                 List chores from grocy
        push               Send completed and rescheduled chores in todo.txt to
                           grocy
        pull               Replace chores in todo.txt with current ones from grocy
        drop               Remove chores from todo-list
    
    options:
      -h, --help           show this help message and exit
      --timeout N          Override the default timeout for each REST call
      --dry-run            perform a trial run with no changes made

    
Let's demonstrate how to use of `chore` on a short todo list:

.. code::

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

First let's see what chores Grocy has for us:

.. code::
 
    $ todo-txt chore ls --all
    Change towels in the bathroom chore:1
    Mop the kitchen floor chore:2
    Take out the trash chore:3
    Vacuum the living room floor chore:4
    Clean the litter box chore:5
    Change the bed sheets chore:6

The --all option gets all chore including the ones that are not overdue or manually scheduled.

Now if we want to have these in our todo.txt we use the pull command:

.. code::

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

.. code::

    $ todo-txt -a do 8    #=> --exit 0
    $ todo-txt -a do 10   #=> --exit 0
    $ todo-txt -a do 11   #=> --exit 0
    $ todo-txt -a do 12   #=> --exit 0

To instead skip a chore, just give it a prio of S instead:

.. code::

    $ todo-txt pri 13 s  #=> --exit 0


When we want to inform Grocy that we have completed the chores we run a
`todo-txt chore push` and remove the completed tasks with a `todo-txt archive`.
As long as completed chores are in our todo.txt a `todo-txt chore pull` will be
prevented so no completed chore gets forgotten.

.. code::

    $ todo-txt chore pull
    Error: chore 1 is marked as done in todo.txt.
     Run "push" and "archive" first. Aborting.
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

For some chores, however we might record the completion automatically and want
the reminder if to do it without manually checking it of. Chores like airing
out the apartment can be tracked with a home automation system and window
sensors. Or running a backup script can call Grocy herself after completion. We
mark these by having the +auto pseudo project in the task.

.. code::

    $ todo-txt add air out appartment +auto chore:42
    9 air out appartment +auto chore:42
    TODO: 9 added.
    $ todo-txt add Run backup script +auto chore:43
    10 Run backup script +auto chore:43
    TODO: 10 added.
    $ todo-txt -a do 9    #=> --exit 0
    $ todo-txt -a do 10    #=> --exit 0
    $ todo-txt chore push    #=> --lines 0

If at some point you want to remove all chores from your todo list, the `drop`
subcommand is your friend.

.. code::

    $ todo-txt ls
    01 Call Mom @Phone +Family
    02 Schedule annual checkup +Health
    03 Outilne chapter 5 +Novel @Computer
    04 Add cover sheets @Office +TPSReports
    05 Download Todo.txt mobile app @Phone
    06 Pick up milk @GroceryStore
    07 Plan backyard herb garden @Home
    08 Mop the kitchen floor chore:2
    09 x 2023-07-26 air out appartment +auto chore:42
    10 x 2023-07-26 Run backup script +auto chore:43
    --
    TODO: 10 of 10 tasks shown
    $ todo-txt chore drop
    Error: chore 42 is marked as done in todo.txt.
     Run "push" and "archive" first. Aborting.
    $ todo-txt archive   #=> --exit 0
    $ todo-txt chore drop
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
