# Copyright 2012-2014 MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License",
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Utilities for choosing which member of a replica set to read from."""

from collections import Mapping, namedtuple

from pymongo.errors import ConfigurationError
from pymongo.server_selectors import (member_with_tags_server_selector,
                                      secondary_with_tags_server_selector,
                                      writable_server_selector)


_PRIMARY = 0
_PRIMARY_PREFERRED = 1
_SECONDARY = 2
_SECONDARY_PREFERRED = 3
_NEAREST = 4


_MONGOS_MODES = (
    'primary',
    'primaryPreferred',
    'secondary',
    'secondaryPreferred',
    'nearest',
)


def _validate_tag_sets(tag_sets):
    """Validate tag sets for a MongoReplicaSetClient.
    """
    if tag_sets is None:
        return tag_sets

    if not isinstance(tag_sets, list):
        raise ConfigurationError((
            "Tag sets %r invalid, must be a list") % (tag_sets,))
    if len(tag_sets) == 0:
        raise ConfigurationError((
            "Tag sets %r invalid, must be None or contain at least one set of"
            " tags") % (tag_sets,))

    for tags in tag_sets:
        if not isinstance(tags, Mapping):
            raise ConfigurationError(
                "Tag set %r invalid, must be an instance of dict, "
                "bson.son.SON or other type that inherits from "
                "collection.Mapping" % (tags,))

    return tag_sets


class ServerMode(object):
    """Base class for all read preferences.
    """

    __slots__ = ("__mongos_mode", "__mode", "__tag_sets")

    def __init__(self, mode, tag_sets=None):
        if mode == _PRIMARY and tag_sets is not None:
            raise ConfigurationError("Read preference primary "
                                     "cannot be combined with tags")
        self.__mongos_mode = _MONGOS_MODES[mode]
        self.__mode = mode
        self.__tag_sets = _validate_tag_sets(tag_sets)

    @property
    def name(self):
        """The name of this read preference.
        """
        return self.__class__.__name__

    @property
    def document(self):
        """Read preference as a document.
        """
        if self.__tag_sets in (None, [{}]):
            return {'mode': self.__mongos_mode}
        return {'mode': self.__mongos_mode, 'tags': self.__tag_sets}

    @property
    def mode(self):
        """The mode of this read preference instance.
        """
        return self.__mode

    @property
    def tag_sets(self):
        """Set ``tag_sets`` to a list of dictionaries like [{'dc': 'ny'}] to
        read only from members whose ``dc`` tag has the value ``"ny"``.
        To specify a priority-order for tag sets, provide a list of
        tag sets: ``[{'dc': 'ny'}, {'dc': 'la'}, {}]``. A final, empty tag
        set, ``{}``, means "read from any member that matches the mode,
        ignoring tags." MongoReplicaSetClient tries each set of tags in turn
        until it finds a set of tags with at least one matching member.

           .. seealso:: `Data-Center Awareness
               <http://www.mongodb.org/display/DOCS/Data+Center+Awareness>`_
        """
        return self.__tag_sets or [{}]

    def __repr__(self):
        return "%s(tag_sets=%r)" % (
            self.name, self.__tag_sets)

    def __eq__(self, other):
        if isinstance(other, ServerMode):
            return (self.mode == other.mode and
                    self.tag_sets == other.tag_sets)
        raise NotImplementedError

    def __ne__(self, other):
        return not self == other


class Primary(ServerMode):
    """Primary read preference.

    * When directly connected to one mongod queries are allowed if the server
      is standalone or a replica set primary.
    * When connected to a mongos queries are sent to the primary of a shard.
    * When connected to a replica set queries are sent to the primary of
      the replica set.
    """

    def __init__(self):
        super(Primary, self).__init__(_PRIMARY)

    def __call__(self, server_descriptions):
        """Return matching ServerDescriptions from a list."""
        return writable_server_selector(server_descriptions)

    def __repr__(self):
        return "Primary"

    def __eq__(self, other):
        if isinstance(other, ServerMode):
            return other.mode == _PRIMARY
        raise NotImplementedError


class PrimaryPreferred(ServerMode):
    """PrimaryPreferred read preference.

    * When directly connected to one mongod queries are allowed to standalone
      servers, to a replica set primary, or to replica set secondaries.
    * When connected to a mongos queries are sent to the primary of a shard if
      available, otherwise a shard secondary.
    * When connected to a replica set queries are sent to the primary if
      available, otherwise a secondary.

    :Parameters:
      - `tag_sets`: The :attr:`~tag_sets` to use if the primary is not
        available.
    """

    def __init__(self, tag_sets=None):
        super(PrimaryPreferred, self).__init__(_PRIMARY_PREFERRED, tag_sets)

    def __call__(self, server_descriptions):
        """Return matching ServerDescriptions from a list."""
        writable_servers = writable_server_selector(server_descriptions)
        if writable_servers:
            return writable_servers
        else:
            return secondary_with_tags_server_selector(
                self.tag_sets,
                server_descriptions)


class Secondary(ServerMode):
    """Secondary read preference.

    * When directly connected to one mongod queries are allowed to standalone
      servers, to a replica set primary, or to replica set secondaries.
    * When connected to a mongos queries are distributed among shard
      secondaries. An error is raised if no secondaries are available.
    * When connected to a replica set queries are distributed among
      secondaries. An error is raised if no secondaries are available.

    :Parameters:
      - `tag_sets`: The :attr:`~tag_sets` to use with this read_preference
    """

    def __init__(self, tag_sets=None):
        super(Secondary, self).__init__(_SECONDARY, tag_sets)

    def __call__(self, server_descriptions):
        """Return matching ServerDescriptions from a list."""
        return secondary_with_tags_server_selector(
            self.tag_sets,
            server_descriptions)


class SecondaryPreferred(ServerMode):
    """SecondaryPreferred read preference.

    * When directly connected to one mongod queries are allowed to standalone
      servers, to a replica set primary, or to replica set secondaries.
    * When connected to a mongos queries are distributed among shard
      secondaries, or the shard primary if no secondary is available.
    * When connected to a replica set queries are distributed among
      secondaries, or the primary if no secondary is available.

    :Parameters:
      - `tag_sets`: The :attr:`~tag_sets` to use with this read_preference
    """

    def __init__(self, tag_sets=None):
        super(SecondaryPreferred, self).__init__(_SECONDARY_PREFERRED, tag_sets)

    def __call__(self, server_descriptions):
        """Return matching ServerDescriptions from a list."""
        secondaries = secondary_with_tags_server_selector(
            self.tag_sets,
            server_descriptions)

        if secondaries:
            return secondaries
        else:
            return writable_server_selector(server_descriptions)


class Nearest(ServerMode):
    """Nearest read preference.

    * When directly connected to one mongod queries are allowed to standalone
      servers, to a replica set primary, or to replica set secondaries.
    * When connected to a mongos queries are distributed among all members of
      a shard.
    * When connected to a replica set queries are distributed among all
      members.

    :Parameters:
      - `tag_sets`: The :attr:`~tag_sets` to use with this read_preference
    """

    def __init__(self, tag_sets=None):
        super(Nearest, self).__init__(_NEAREST, tag_sets)

    def __call__(self, server_descriptions):
        """Return matching ServerDescriptions from a list."""
        return member_with_tags_server_selector(
            self.tag_sets or [{}],
            server_descriptions)


_ALL_READ_PREFERENCES = (Primary, PrimaryPreferred,
                         Secondary, SecondaryPreferred, Nearest)

def make_read_preference(mode, tag_sets):
    if mode == _PRIMARY:
        if tag_sets not in (None, [{}]):
            raise ConfigurationError("Read preference primary "
                                     "cannot be combined with tags")
        return Primary()
    return _ALL_READ_PREFERENCES[mode](tag_sets)


_MODES = (
    'PRIMARY',
    'PRIMARY_PREFERRED',
    'SECONDARY',
    'SECONDARY_PREFERRED',
    'NEAREST',
)


ReadPreference = namedtuple("ReadPreference", _MODES)(
    Primary(), PrimaryPreferred(), Secondary(), SecondaryPreferred(), Nearest())
"""An enum that defines the read preference modes supported by PyMongo.

See :doc:`/examples/high_availability` for code examples.

A read preference is used in three cases:

:class:`~pymongo.mongo_client.MongoClient` connected to a single mongod:

- ``PRIMARY``: Queries are allowed if the server is standalone or a replica
  set primary.
- All other modes allow queries to standalone servers, to a replica set
  primary, or to replica set secondaries.

:class:`~pymongo.mongo_client.MongoClient` initialized with the
``replicaSet`` option:

- ``PRIMARY``: Read from the primary. This is the default, and provides the
  strongest consistency. If no primary is available, raise
  :class:`~pymongo.errors.AutoReconnect`.

- ``PRIMARY_PREFERRED``: Read from the primary if available, or if there is
  none, read from a secondary matching your choice of ``tag_sets`` and
  ``local_threshold_ms``.

- ``SECONDARY``: Read from a secondary matching your choice of ``tag_sets`` and
  ``local_threshold_ms``. If no matching secondary is available,
  raise :class:`~pymongo.errors.AutoReconnect`.

- ``SECONDARY_PREFERRED``: Read from a secondary matching your choice of
  ``tag_sets`` and ``local_threshold_ms`` if available, otherwise
  from primary (regardless of the primary's tags and local threshold).

- ``NEAREST``: Read from any member matching your choice of ``tag_sets`` and
  ``local_threshold_ms``.

:class:`~pymongo.mongo_client.MongoClient` connected to a mongos, with a
sharded cluster of replica sets:

- ``PRIMARY``: Read from the primary of the shard, or raise
  :class:`~pymongo.errors.OperationFailure` if there is none.
  This is the default.

- ``PRIMARY_PREFERRED``: Read from the primary of the shard, or if there is
  none, read from a secondary matching your choice of ``tag_sets``.

- ``SECONDARY``: Read from a secondary matching your choice of ``tag_sets``,
  or raise :class:`~pymongo.errors.OperationFailure` if there is none.

- ``SECONDARY_PREFERRED``: Read from a secondary matching your choice of
  ``tag_sets``, otherwise from primary.

- ``NEAREST``: Read from any member matching your choice of ``tag_sets``.

.. note:: ``local_threshold_ms`` is ignored when talking to a
  replica set *through* a mongos. The equivalent is the
  `localThreshold <http://docs.mongodb.org/manual/reference/mongos/#cmdoption--localThreshold>`_
  command line option.
"""


def read_pref_mode_from_name(name):
    """Get the read preference mode from mongos/uri name.
    """
    return _MONGOS_MODES.index(name)


class MovingAverage(object):
    """Tracks an exponentially-weighted moving average."""
    def __init__(self):
        self.average = None

    def add_sample(self, sample):
        if self.average is None:
            self.average = sample
        else:
            # The Server Selection Spec requires an exponentially weighted
            # average with alpha = 0.2.
            self.average = 0.8 * self.average + 0.2 * sample

    def get(self):
        """Get the calculated average, or None if no samples yet."""
        return self.average

    def reset(self):
        self.average = None
