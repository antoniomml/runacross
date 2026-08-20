from boto3.session import Session

from runacross import Account, map_accounts
from runacross.organizations import list_accounts


def who_am_i(session: Session, _account: Account) -> str:
    sts = session.client("sts")
    return sts.get_caller_identity()["Arn"]


def main() -> None:
    accounts = list_accounts(
        organization_id="o-exampleorgid",
        exclude_accounts=["111111111111"],
    )
    results = map_accounts(
        who_am_i,
        accounts=accounts,
        role_name="SecurityAuditRole",
    )

    for result in results:
        if result.success:
            print(f"{result.account.id}: {result.value}")
        else:
            print(f"{result.account.id}: {result.phase}: {result.error}")


if __name__ == "__main__":
    main()
