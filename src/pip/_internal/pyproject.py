from __future__ import absolute_import

import io
import logging
import os
import sys

from pip._vendor import pytoml, six

from pip._internal.exceptions import InstallationError
from pip._internal.utils.typing import MYPY_CHECK_RUNNING

if MYPY_CHECK_RUNNING:
    from typing import Any, Dict, List, Optional, Tuple

    Pep517Data = Tuple[str, List[str]]


logger = logging.getLogger(__name__)


def _is_list_of_str(obj):
    # type: (Any) -> bool
    return (
        isinstance(obj, list) and
        all(isinstance(item, six.string_types) for item in obj)
    )


def make_pyproject_path(setup_py_dir):
    # type: (str) -> str
    path = os.path.join(setup_py_dir, 'pyproject.toml')

    # Python2 __file__ should not be unicode
    if six.PY2 and isinstance(path, six.text_type):
        path = path.encode(sys.getfilesystemencoding())

    return path


def read_pyproject_toml(path):
    # type: (str) -> Optional[Dict[str, str]]
    """
    Read a project's pyproject.toml file.

    :param path: The path to the pyproject.toml file.

    :return: The "build_system" value specified in the project's
        pyproject.toml file.
    """
    with io.open(path, encoding="utf-8") as f:
        pp_toml = pytoml.load(f)
    build_system = pp_toml.get("build-system")

    return build_system


def make_editable_error(req_name, reason):
    """
    :param req_name: the name of the requirement.
    :param reason: the reason the requirement is being processed as
        pyproject.toml-style.
    """
    message = (
        'Error installing {!r}: editable mode is not supported for '
        'pyproject.toml-style projects. This project is being processed '
        'as pyproject.toml-style because {}. '
        'See PEP 517 for the relevant specification.'
    ).format(req_name, reason)
    return InstallationError(message)


def get_build_system_requires(build_system, req_name):
    if build_system is None:
        return None

    # Ensure that the build-system section in pyproject.toml conforms
    # to PEP 518.
    error_template = (
        "{package} has a pyproject.toml file that does not comply "
        "with PEP 518: {reason}"
    )

    # Specifying the build-system table but not the requires key is invalid
    if "requires" not in build_system:
        raise InstallationError(
            error_template.format(package=req_name, reason=(
                "it has a 'build-system' table but not "
                "'build-system.requires' which is mandatory in the table"
            ))
        )

    # Error out if requires is not a list of strings
    requires = build_system["requires"]
    if not _is_list_of_str(requires):
        raise InstallationError(error_template.format(
            package=req_name,
            reason="'build-system.requires' is not a list of strings.",
        ))

    return requires


def resolve_pyproject_toml(
    build_system,  # type: Optional[Dict[str, Any]]
    has_pyproject,  # type: bool
    has_setup,  # type: bool
    use_pep517,  # type: Optional[bool]
    editable,  # type: bool
    req_name,  # type: str
):
    # type: (...) -> Tuple[Optional[List[str]], Optional[Pep517Data]]
    """
    Return how a pyproject.toml file's contents should be interpreted.

    :param build_system: the "build_system" value specified in a project's
        pyproject.toml file, or None if the project either doesn't have the
        file or does but the file doesn't have a [build-system] table.
    :param has_pyproject: whether the project has a pyproject.toml file.
    :param has_setup: whether the project has a setup.py file.
    :param use_pep517: whether the user requested PEP 517 processing.  None
        means the user didn't explicitly specify.
    :param editable: whether editable mode was requested for the requirement.
    :param req_name: the name of the requirement we're processing (for
        error reporting).

    :return: a tuple (requires, pep517_data), where `requires` is the list
      of build requirements from pyproject.toml (or else None).  The value
      `pep517_data` is None if `use_pep517` is False.  Otherwise, it is the
      tuple (backend, check), where `backend` is the name of the PEP 517
      backend and `check` is the list of requirements we should check are
      installed after setting up the build environment.
    """
    # The following cases must use PEP 517
    # We check for use_pep517 being non-None and falsey because that means
    # the user explicitly requested --no-use-pep517.  The value 0 as
    # opposed to False can occur when the value is provided via an
    # environment variable or config file option (due to the quirk of
    # strtobool() returning an integer in pip's configuration code).
    if editable and use_pep517:
        raise make_editable_error(
            req_name, 'PEP 517 processing was explicitly requested'
        )
    elif has_pyproject and not has_setup:
        if use_pep517 is not None and not use_pep517:
            raise InstallationError(
                "Disabling PEP 517 processing is invalid: "
                "project does not have a setup.py"
            )
        if editable:
            raise make_editable_error(
                req_name, 'it has a pyproject.toml file and no setup.py'
            )
        use_pep517 = True
    elif build_system and "build-backend" in build_system:
        if editable:
            if use_pep517 is None:
                message = (
                    'Error installing {!r}: editable mode is not supported '
                    'for pyproject.toml-style projects. '
                    'This project is pyproject.toml-style because it has a '
                    'pyproject.toml file and a "build-backend" key for the '
                    '[build-system] table, but editable mode is undefined '
                    'for pyproject.toml-style projects. '
                    'Since the project has a setup.py, you may pass '
                    '--no-use-pep517 to opt out of pyproject.toml-style '
                    'processing. However, this is an unsupported combination. '
                    'See PEP 517 for details on pyproject.toml-style projects.'
                ).format(req_name)
                raise InstallationError(message)

            # The case of `editable and use_pep517` being true was already
            # handled above.
            assert not use_pep517
            message = (
                'Installing {!r} in editable mode, which is not supported '
                'for pyproject.toml-style projects: '
                'this project is pyproject.toml-style because it has a '
                'pyproject.toml file and a "build-backend" key for the '
                '[build-system] table, but editable mode is undefined '
                'for pyproject.toml-style projects. '
                'See PEP 517 for details on pyproject.toml-style projects.'
            ).format(req_name)
            logger.warning(message)
        elif use_pep517 is not None and not use_pep517:
            raise InstallationError(
                "Disabling PEP 517 processing is invalid: "
                "project specifies a build backend of {} "
                "in pyproject.toml".format(
                    build_system["build-backend"]
                )
            )
        else:
            use_pep517 = True

    # If we haven't worked out whether to use PEP 517 yet, and the user
    # hasn't explicitly stated a preference, we do so if the project has
    # a pyproject.toml file (provided editable mode wasn't requested).
    elif use_pep517 is None:
        if has_pyproject and editable:
            message = (
                'Error installing {!r}: editable mode is not supported for '
                'pyproject.toml-style projects. pip is processing this '
                'project as pyproject.toml-style because it has a '
                'pyproject.toml file. Since the project has a setup.py and '
                'the pyproject.toml has no "build-backend" key for the '
                '[build-system] table, you may pass --no-use-pep517 to opt '
                'out of pyproject.toml-style processing. '
                'See PEP 517 for details on pyproject.toml-style projects.'
            ).format(req_name)
            raise InstallationError(message)

        use_pep517 = has_pyproject

    # At this point, we know whether we're going to use PEP 517.
    assert use_pep517 is not None

    requires = get_build_system_requires(build_system, req_name=req_name)

    # If we're using the legacy code path, there is nothing further
    # for us to do here.
    if not use_pep517:
        return (requires, None)

    if build_system is None:
        # Either the user has a pyproject.toml with no build-system
        # section, or the user has no pyproject.toml, but has opted in
        # explicitly via --use-pep517.
        # In the absence of any explicit backend specification, we
        # assume the setuptools backend that most closely emulates the
        # traditional direct setup.py execution, and require wheel and
        # a version of setuptools that supports that backend.

        requires = ["setuptools>=40.8.0", "wheel"]
        build_system = {
            "build-backend": "setuptools.build_meta:__legacy__",
        }

    # If we're using PEP 517, we have build system information (either
    # from pyproject.toml, or defaulted by the code above).
    # Note that at this point, we do not know if the user has actually
    # specified a backend, though.
    assert build_system is not None

    backend = build_system.get("build-backend")
    check = []  # type: List[str]
    if backend is None:
        # If the user didn't specify a backend, we assume they want to use
        # the setuptools backend. But we can't be sure they have included
        # a version of setuptools which supplies the backend, or wheel
        # (which is needed by the backend) in their requirements. So we
        # make a note to check that those requirements are present once
        # we have set up the environment.
        # This is quite a lot of work to check for a very specific case. But
        # the problem is, that case is potentially quite common - projects that
        # adopted PEP 518 early for the ability to specify requirements to
        # execute setup.py, but never considered needing to mention the build
        # tools themselves. The original PEP 518 code had a similar check (but
        # implemented in a different way).
        backend = "setuptools.build_meta:__legacy__"
        check = ["setuptools>=40.8.0", "wheel"]

    return (requires, (backend, check))


def load_pyproject_toml(
    use_pep517,  # type: Optional[bool]
    editable,  # type: bool
    pyproject_toml,  # type: str
    setup_py,  # type: str
    req_name  # type: str
):
    # type: (...) -> Tuple[Optional[List[str]], Optional[Pep517Data]]
    """Load the pyproject.toml file.

    Parameters:
        use_pep517 - Has the user requested PEP 517 processing? None
                     means the user hasn't explicitly specified.
        editable - Whether editable mode was requested for the requirement.
        pyproject_toml - Location of the project's pyproject.toml file
        setup_py - Location of the project's setup.py file
        req_name - The name of the requirement we're processing (for
                   error reporting)

    Returns: (requires, pep_517_data)
      requires: requirements from pyproject.toml (can be None).
      pep_517_data: None if we should use the legacy code path, otherwise:
        (
            name of PEP 517 backend,
            requirements we should check are installed after setting up
            the build environment
        )
    """
    has_pyproject = os.path.isfile(pyproject_toml)
    has_setup = os.path.isfile(setup_py)

    if has_pyproject:
        build_system = read_pyproject_toml(pyproject_toml)
    else:
        build_system = None

    return resolve_pyproject_toml(
        build_system=build_system,
        has_pyproject=has_pyproject,
        has_setup=has_setup,
        use_pep517=use_pep517,
        editable=editable,
        req_name=req_name,
    )
