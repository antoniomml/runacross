"""Discover Identity Center profiles locally, then execute with Profile auth."""

from boto3.session import Session

from runacross import Account, Profile, map_accounts, show_progress
from runacross.profiles import list_accounts


def who_am_i(session: Session, _account: Account) -> str:
    return session.client("sts").get_caller_identity()["Arn"]


def main() -> None:
    accounts = list_accounts(
        pattern="AWS-Infosec-{account_id}",
        sso_session="control-tower",
        limit=3,
    )
    results = map_accounts(
        who_am_i,
        accounts=accounts,
        auth=Profile("AWS-Infosec-{account_id}", verify_account_id=True),
        on_result=show_progress(),
    )
    for result in results:
        if result.success:
            print(f"{result.account.id}: {result.value}")
        else:
            print(f"{result.account.id}: {result.phase}: {result.error}")


if __name__ == "__main__":
    main()
