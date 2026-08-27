import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import bcrypt
from sqlalchemy import select

from app.models import Group, User, UserGroup
from extensions import sync_session_factory


def seed():
    with sync_session_factory() as s:
        # -- 1. Groups ----------------------------------------------------------
        admin_group = s.execute(
            select(Group).where(Group.idgroup == 1)
        ).scalar_one_or_none()
        if not admin_group:
            admin_group = Group(
                idgroup=1, name="admin", desc="Administrative group with full access"
            )
            s.add(admin_group)
            s.commit()
        else:
            admin_group.name = "admin"
            admin_group.desc = "Administrative group with full access"
            s.commit()

        regular_group = s.execute(
            select(Group).where(Group.idgroup == 2)
        ).scalar_one_or_none()
        if not regular_group:
            regular_group = Group(
                idgroup=2, name="regular_users", desc="Regular users group"
            )
            s.add(regular_group)
            s.commit()
        else:
            regular_group.name = "regular_users"
            regular_group.desc = "Regular users group"
            s.commit()

        print(
            f"Groups: admin (id={admin_group.idgroup}), regular_users (id={regular_group.idgroup})"
        )

        # -- 2. Admin user (idu=1) ----------------------------------------------
        admin_user = s.execute(select(User).where(User.idu == 1)).scalar_one_or_none()
        if not admin_user:
            pass_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")
            admin_user = User(
                idu=1,
                nick="admin",
                pass_hash=pass_hash,
                name="System",
                lastname="Administrator",
                perm=["ADM"],
                email="admin@localhost",
            )
            s.add(admin_user)
            s.commit()
            print(f"Created admin user (idu={admin_user.idu}, nick=admin)")
        else:
            admin_user.nick = "admin"
            admin_user.pass_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(
                "utf-8"
            )
            admin_user.name = "System"
            admin_user.lastname = "Administrator"
            admin_user.perm = ["ADM"]
            admin_user.email = "admin@localhost"
            s.commit()
            print(f"Updated admin user (idu={admin_user.idu}, nick={admin_user.nick})")

        # -- 3. Assign admin user to admin group --------------------------------
        membership = s.execute(
            select(UserGroup).where(
                UserGroup.iduser == admin_user.idu,
                UserGroup.idgroup == admin_group.idgroup,
            )
        ).scalar_one_or_none()
        if not membership:
            membership = UserGroup(iduser=admin_user.idu, idgroup=admin_group.idgroup)
            s.add(membership)
            s.commit()
            print(f"Assigned admin (idu=1) to admin group (id={admin_group.idgroup})")
        else:
            print("Admin already assigned to admin group")


if __name__ == "__main__":
    seed()
