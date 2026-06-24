from contextlib import contextmanager
from collections.abc import Generator

from psycopg2 import connect
from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor

from entities import Actor, ConnectionConfig, Movie  # pyright: ignore[reportImplicitRelativeImport]


@contextmanager
def create_connection(
    config: ConnectionConfig,
) -> Generator[Connection, None, None]:
    yield connect(**{("user" if k == "username" else k): v for k, v in config.model_dump().items()})  # pyright: ignore[reportAny]


def query_movies(conn: Connection, keywords: str) -> list[Movie]:
    """
    Return all movies whose title contains *keywords* (case-insensitive).

    Sorted by title ASC, then year ASC (NULLs last).
    Each movie's actor_names list is sorted alphabetically.
    """

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute(
        """
            SELECT
                t.tconst, t."primaryTitle" AS title, t.genres, t."startYear" AS year
            FROM tmovies t
            WHERE t."primaryTitle" ILIKE %s
            ORDER BY t."primaryTitle" ASC, t."startYear" ASC
        """,
        [f"%{keywords}%"],
    )

    movies: dict[str, Movie] = {rec["tconst"]: Movie.model_validate(rec) for rec in cursor}

    cursor.execute(
        """
            SELECT t.tconst, n.primaryname AS name
            FROM
                tmovies t
                JOIN tprincipals p ON p.tconst = t.tconst
                    AND p.category IN ('actor', 'actress')
                JOIN nbasics n ON n.nconst = p.nconst
            WHERE
                t.tconst IN (%s)
        """,
        [",".join(movies.keys())],
    )

    for tconst in movies.keys():
        movies[tconst].actor_names = [rec["name"] for rec in cursor if rec["tconst"] == tconst]
        movies[tconst].actor_names.sort()

    return [*movies.values()]


def query_actors(conn: Connection, keywords: str) -> list[Actor]:
    """
    Return the 5 most relevant actors/actresses whose name contains *keywords*.

    Sorted by total movie count DESC, then name ASC.
    Each actor's played_in list contains up to 5 titles (most recent first,
    NULLs last, then title ASC for ties).
    Each actor's costar_name_to_count dict contains up to 5 costars
    (most shared movies first, then name ASC).
    All limits and ordering are enforced in SQL.
    """

    raise NotImplementedError
