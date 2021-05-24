# Use Profiles to streamline Python client setup

## What problem do profiles solve?

Profiles provide a shorthand for constructing clients. A profile stores client
parameters in a file and gives them an alias, so that this:

```py
from tiled.client import from_uri
from tiled.client.cache import Cache

catalog = from_uri("http://some_server_address", cache=Cache.on_disk("path/to/cache"))
```

can be replaced with the more memorable and succinct

```py
from tiled.client import from_profile

catalog = from_profile("my_catalog")
```

where `my_catalog` can be any name you wish.

## Where are profiles configured?

Profiles are configured in YAML files located in any of several locations.
To list where Tiled looks for Profiles on your system, use the command line:

```
$ tiled profile paths
```

or Python:

```py
>>> from tiled.profiles import paths
>>> paths
```

Within these directories, you may have:

* Any number of configuration files
* Named whatever you want
* With one or more profiles per configuration file

That is, you can keep one file with all your profiles or organize them
by grouping them into several separate files, named whatever you want.

The paths later in the list---"closer to the user"---take precedence in the
event of name collisions. See the section on Merging Rules below for details.

```{note}
Tiled always looks in three places for profiles:

1. A system-wide directory. This is used by *administrators* to
   distribute profiles that all users can see.
2. A directory in the currently active Python software environment
   (for example, the conda environment). This is used by
   *software packages* to distribute profiles that support their
   software.
3. A user-controlled directory (a subdirectory of `$HOME`). This is
   for users' personal productivity.

The exact locations depend on which operating system you are using and other
system-specific details, which is why we can't list them here.
```

## Create and use a profile

Place a file in one of the directories listed in the previous section.
The last directory in the list, the "user" one, is a good place to start.
The filename can be anything. To start, `profiles.yml` is as good a name as any.

Give in the content:

```yaml
# profiles.yml
local:
   uri: "http://localhost:8000"
local_dask:
   uri: "http://localhost:8000"
   structure_clients: "dask"
```

Now we have two profiles that aim at a local server, one with default (numpy)
clients and one with dask clients. We can use them like:

```py
from tiled.client import from_profile

catalog = from_profile("local")
lazy_catalog = from_profile("local_dask")
```

## List profiles

To list profiles on your system...

From the shell:

```
$ tiled profile list
```

From Python:

```py
>>> from tiled.profiles import list_profiles
>>> list_profiles()
```

## View profiles

To show the contents of a profile...

From the shell:

```
$ tiled profile show PROFILE_NAME
```

From Python:

```py
>>> from tiled.profiles import load_profiles
>>> load_profiles()  # show all, given as {profile_name: (filepath, content)}
>>> load_profiles()[PROFILE_NAME]  # show one (filepath, content)
```

## Merging rules

Situation #1: In the event of a name collision *within one file* like:

```yaml
my_profile:
   ...
my_proifile:  # oops, reused the same name
   ...
```

the second one will win. (This is just how YAML works. We wish we could
issue a warning or something to let you know that something looks off,
but we have no way to do that without going to great lengths.)

Situation #2: In the event of a name collision between files in different
directories, the one in the directory "closer to the user"---later in the list
of paths---will take precedence. No warning will be issued. This the normal way
for users to override a default system- or environment-level configuration with
their own preferences.

Situation #3: In the event of a name collision between two files in the same directory:

```yaml
# some/directory/some_profiles.yaml
my_profile:
    ...
```

```yaml
# some/directory/yet_more_profiles.yaml
my_profile:
    ...
```

Tiled has no way of guessing which is "right" so it refuses to load either one,
and it issues a warning indicating that this profile will be skipped until
the issue is resolved.

If the collision occurs in the system or software environment directory and you
do not have the access necessary to edit those configurations and resolve the
issue, you can override the problematic name by defining a new profile with that
name in your user configuration directory. As described in Situation #2, the version
in the user configuration directory will take precedence.  The collision will
therefore become irrelevant and will be ignored.

If the collision occurs in the user directory, then you (of course) have
the access necessary to fix it, and you should.