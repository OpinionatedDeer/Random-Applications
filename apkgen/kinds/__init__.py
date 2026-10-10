"""App kinds. Each kind is a subpackage providing:

    HELP            one-line description for the CLI
    PACKAGE_PREFIX  package name prefix; app N is PACKAGE_PREFIX + str(N)
    add_arguments(parser)          kind-specific CLI flags
    options_from_args(args)        -> frozen, picklable options (raise ValueError if invalid)
    prepare(tc, opts, workdir)     optional; runs once in the main process before the pool
    make_spec(i, opts, tc, prepared) -> ApkSpec; runs in a worker process
"""

KINDS = ("normal",)
