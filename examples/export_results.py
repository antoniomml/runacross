"""Serialize execution results without choosing a CLI or report format."""

import json

from boto3.session import Session

from runacross import Account, map_accounts


def who_am_i(session: Session, _account: Account) -> str:
    return session.client("sts").get_caller_identity()["Arn"]


def main() -> None:
    results = map_accounts(
        who_am_i,
        accounts=["111111111111", "222222222222"],
        role_name="SecurityAuditRole",
    )
    print(json.dumps(results.summary()))
    print(json.dumps(results.to_dicts(), indent=2))


if __name__ == "__main__":
    main()
