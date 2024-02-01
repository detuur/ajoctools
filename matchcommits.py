#!/usr/bin/env python3

"""
matchcommits.py v0.3
AUTHOR: detuur(ajoc)
LICENSE: MIT
"""

import os
import configparser
import argparse
from git import Repo

args = None

def main():
    global args
    parser = argparse.ArgumentParser(description="""Matches commits between odoo Community and Enterprise branches.
                                                    Run it from your Community repo when in a detached HEAD to find
                                                    the Enterprise commit that is nearest in time so that you can run
                                                    odoo as it was when these commits were merged.""")

    parser.add_argument('--branch', '-b', help="Search from the tip of this branch. When omitted, uses `master` as default.")
    parser.add_argument('--commit', '-C', action='store_true', help="Search from this commit. Takes priority over --branch.")
    parser.add_argument('--dry-run', '-n', action='store_true', help="Do not automatically check out the found commit.")
    parser.add_argument('--reverse', '-r', action='store_true', help="Reverse behaviour: find the matching Community commit to the current Enterprise commit.")
    parser.add_argument('--enterprise-path', '-e', help="If no Enterprise path is specified, it will be extracted from your odoo.rc file.")
    parser.add_argument('--community-path', '-p', help="If no Community path is specified, it will assume the current directory.")
    parser.add_argument('--odoorc-path', '-c', help="If no odoo.rc path is specified, it will be extracted from the $ODOO_RC env var.")
    parser.add_argument('--search-out-of-order', '-o', action='store_true', help="Do not discard out-of-order Enterprise commits even if Community is in-order.")
    parser.add_argument('--always-after', '-A', action='store_true', help="Always get the first Enterprise commit after the current Community commit.")
    parser.add_argument('--always-before', '-B', action='store_true', help="Always get the first Enterprise commit before the current Community commit.")
    parser.add_argument('--check', action='store_true', help="Does not attempt to find a matching commit, just reports the current state.")
    parser.add_argument('--verbose', '-v', action='count', default=0, help="Verbosity. Use multiple v's for higher verbosity levels.")
    parser.add_argument('--silent', '-s', action='store_true', help="Don't print anything. This does nothing with --dry-run or --verbose.")
    args = parser.parse_args()

    branch = args.commit or args.branch or "master"
    enterprise_path = args.enterprise_path or get_enterprise_path_from_config(args.odoorc_path)
    if not enterprise_path:
        return

    community_repo = Repo(args.community_path) if args.community_path else Repo('.')
    enterprise_repo = Repo(enterprise_path)

    if args.reverse:
        source_repo = enterprise_repo
        target_repo = community_repo
        source_str = "Enterprise"
        target_str = "Community"
    else:
        source_repo = community_repo
        target_repo = enterprise_repo
        source_str = "Community"
        target_str = "Enterprise"

    source_commit = source_repo.head.commit

    if args.check:
        check_mode(source_commit, source_str, target_repo, target_str)

    (closest_target_commit, second_closest_target_commit) = find_closest_commits(target_repo, source_commit, branch)

    print_commit_info(source_commit, f"Current {source_str}")
    print_commit_info(closest_target_commit, f"\nClosest {target_str}")

    if not second_closest_target_commit:
        prn(f"(This is the tip of the branch `{branch}`)")

    print_commit_comp(source_commit, closest_target_commit, target_str)

    if second_closest_target_commit and args.verbose > 0:
        print_commit_info(second_closest_target_commit, f"\nSecond closest {target_str}")
        print_commit_comp(source_commit, second_closest_target_commit, target_str, warn=False)

    if args.dry_run:
        prn("\nDry run; no commits checked out.")
        return

    prn("\nChecking out . . . ", end="", flush=True)
    target_repo.git.checkout(closest_target_commit)
    prn("Done.")


def print_commit_info(commit, commit_name):
    prn(f"{commit_name} commit: {commit.hexsha}")
    prn(f"Title: {commit.summary}")
    prn(f"Authored date: {commit.authored_datetime.isoformat()}", verbosity=1)
    prn(f"Committed date: {color.YELLOW}{commit.committed_datetime.isoformat()}{color.END}")

def check_mode(source_commit, source_str, target_repo, target_str):
    print_commit_info(source_commit, source_str)
    print_commit_info(target_repo.head.commit, f"\n{target_str}")
    print_commit_comp(source_commit, target_repo.head.commit, target_str)
    exit()

def print_commit_comp(source_commit, target_commit, target_str, warn=True):
    ref = source_commit.committed_datetime
    comp = target_commit.committed_datetime
    diff = abs(ref - comp)
    oldyounger = "younger" if ref < comp else "older"

    if diff.days:
        prn(f"{color.BOLD}{color.RED}This {target_str} commit is {diff.days} day(s) {oldyounger}{', ensure that this is correct' if warn else ''}.{color.END}")
    else:
        td = time_diff(ref,comp)
        prn(f"{color.YELLOW if td['hours'] or td['minutes'] else color.GREEN}This {target_str} commit is {time_diff_string(td)} {oldyounger}.{color.END}")

def time_diff(t1, t2):
    diff = abs(t1 - t2)
    return {
        "hours": f"{diff.seconds // 3600} hour(s)" if diff.seconds // 3600 else None,
        "minutes": f"{diff.seconds % 3600 // 60} minute(s)" if diff.seconds // 60 else None,
        "seconds": f"{diff.seconds % 60} second(s)"
    }

def time_diff_string(td):
    return ''.join(sum([[s,', '] for s in [td["hours"], td["minutes"], td["seconds"]] if s], [])[:-1])

def find_closest_commits(repo, target_commit, branch):
    target_commit_datetime = target_commit.committed_datetime
    target_ooo = False #Whether target commit is an out-of-order commit

    prn(f"Determining if target commit is out-of-order... ", end="", verbosity=2)
    count = 200
    next_commit = target_commit
    while count:
        count -= 1
        next_commit = next_commit.parents[0]
        if next_commit.committed_datetime > target_commit_datetime:
            target_ooo = True
            break
    prn("yes" if target_ooo else "no", verbosity=2)

    if args.search_out_of_order and not target_ooo:
        prn(f"Treating target as out-of-order anyway because of --search-out-of-order flag", verbosity=2)
        target_ooo=True

    prn(f"Starting to build search stack...", verbosity=2)
    stack = [repo.commit(branch) if branch else repo.head.commit]
    ooo_commits = []
    count = -1
    while count:
        next_commit = stack[-1].parents[0]
        prn(f"[{count:06d}] Next commit: {next_commit.hexsha[:8]} at {next_commit.committed_datetime.isoformat()}", verbosity=2)
        while len(stack) and next_commit.committed_datetime > stack[0].committed_datetime:
            timestr = time_diff_string(time_diff(next_commit.committed_datetime, stack[0].committed_datetime))
            prn(f"Commit is older than parent ({next_commit.hexsha[:8]}) by {timestr}. Classifying parent as out-of-order.", verbosity=2)
            ooo_commits.append(stack.pop())
        if next_commit.committed_datetime < target_commit_datetime and count < 0:
            prn(f"Commit date before target, starting countdown.", verbosity=2)
            count = 200
        if count > 0 and next_commit.committed_datetime > target_commit_datetime:
            prn(f"Commit date after target, resetting countdown.", verbosity=2)
            count = -1
        stack.append(next_commit)
        count -= 1

    if target_ooo:
            stack += ooo_commits
    if args.always_after:
        stack = [c for c in stack if c.committed_datetime >= target_commit_datetime]
    elif args.always_before:
        stack = [c for c in stack if c.committed_datetime < target_commit_datetime]
    stack.sort(key=lambda c: abs(c.committed_datetime - target_commit_datetime))

    return (stack[0], stack[1] if len(stack) > 1 else None)

def get_enterprise_path_from_config(odoorc_path):
    env_path = os.environ.get('ODOO_RC')

    if not odoorc_path:
        if env_path is None:
            prn(f"{color.RED}No Enterprise or odoo.rc path supplied, and the ODOO_RC environment variable is not set.{color.END}")
            return None
        odoorc_path = env_path

    if not os.path.isfile(odoorc_path):
        prn(f"{color.RED}Odoo configuration file not found at `{odoorc_path}`.{color.END}")
        return None

    config = configparser.ConfigParser()
    config.read(odoorc_path)

    if 'addons_path' not in config['options']:
        prn(f"{color.RED}Config file at `{odoorc_path}` does not contain 'addons_path' key.{color.END}")
        return None

    addon_paths = config['options']['addons_path'].split(',')

    # Search for the 'enterprise' folder path in the list of paths
    enterprise_path = next((path.strip() for path in addon_paths if path.endswith('/enterprise')), None)

    if enterprise_path is None:
        prn(f"{color.RED}Path for 'enterprise' folder not found in 'addons_path' variable in the config file at `{odoorc_path}`.{color.END}")
        return None

    return enterprise_path

def prn(str, end=None, flush=None, verbosity=0):
    if args.silent and not (args.verbose or args.dry_run):
        return
    if args.verbose >= verbosity:
        print(str, end=end, flush=flush)

class color:
   PURPLE = '\033[95m'
   CYAN = '\033[96m'
   DARKCYAN = '\033[36m'
   BLUE = '\033[94m'
   GREEN = '\033[92m'
   YELLOW = '\033[93m'
   RED = '\033[91m'
   BOLD = '\033[1m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'

if __name__ == "__main__":
    main()
