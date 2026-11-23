"""Run the original regression suite and the bypass delivery scenarios.

This is the runtime manifest's verify entry: it keeps the full original
unittest regression and then exercises the bypass fixture, propagating any
failure as a non-zero exit status.
"""
import check_bypass_fixture
import check_project


def main():
    regression = check_project.main()
    check_bypass_fixture.main()
    return regression


if __name__ == '__main__':
    raise SystemExit(main())
