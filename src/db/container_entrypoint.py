"""DB-only container launcher; safely handles passwords containing URL characters."""
import os
import sys
from sqlalchemy.engine import URL


def main():
    if not os.environ.get("DATT_DATABASE_URL"):
        os.environ["DATT_DATABASE_URL"] = URL.create(
            "postgresql+psycopg", username=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"], host=os.environ["POSTGRES_HOST"],
            port=int(os.environ.get("POSTGRES_PORT", "5432")), database=os.environ["POSTGRES_DB"],
        ).render_as_string(hide_password=False)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
