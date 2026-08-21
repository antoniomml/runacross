from boto3.session import Session

from runacross import Account, Profile, map_accounts


def who_am_i(session: Session, _account: Account) -> str:
    sts = session.client("sts")
    return sts.get_caller_identity()["Arn"]


def main() -> None:
    results = map_accounts(
        who_am_i,
        accounts=[
            "111111111111",
            "222222222222",
        ],
        auth=Profile("{account_id}-script-SecurityAudit"),
    )

    for result in results:
        if result.success:
            print(f"{result.account.id}: {result.value}")
        else:
            print(f"{result.account.id}: {result.phase}: {result.error}")


if __name__ == "__main__":
    main()
