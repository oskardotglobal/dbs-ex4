from collections.abc import Generator
from contextlib import contextmanager

from psycopg2 import connect
from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor

from entities import (  # pyright: ignore[reportImplicitRelativeImport]
    Actor,
    ConnectionConfig,
    Movie,
)


@contextmanager
def create_connection(
    config: ConnectionConfig,
) -> Generator[Connection, None, None]:
    yield connect(
        **{
            ("user" if k == "username" else k): v
            for k, v in config.model_dump().items()
        }
    )  # pyright: ignore[reportAny]


def query_movies(conn: Connection, keywords: str) -> list[Movie]:
    """
    Return all movies whose title contains *keywords* (case-insensitive).

    Sorted by title ASC, then year ASC (NULLs last).
    Each movie's actor_names list is sorted alphabetically.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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

        movies: dict[str, Movie] = {
            rec["tconst"]: Movie.model_validate(rec) for rec in cursor
        }

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
            movies[tconst].actor_names = [
                rec["name"] for rec in cursor if rec["tconst"] == tconst
            ]
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

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            select
               	n.primaryname as name,
               	n.nconst as nconst
            from
           	    tprincipals t
               	join nbasics n
               	on t.nconst = n.nconst
            where
               	n.primaryname ilike %s and
               	t.category IN ('actor', 'actress')
            group by
           	    n.nconst
            order by
                cardinality(array_agg(t.tconst)) desc, n.primaryname asc
            limit 5;
            """,
            [f"%{keywords}%"],
        )

        actors: dict[str, Actor] = {
            rec["nconst"]: (
                Actor.model_validate({"nconst": rec["nconst"], "name": rec["name"]})
            )
            for rec in cursor
        }

        # For every actor
        for actor_id in actors:
            # Get films in which the actor has appeared
            cursor.execute(
                """
                    select
                       	t2."primaryTitle" as title
                    from
                       	tprincipals t
                       	join tmovies t2
                       	on t.tconst = t2.tconst
                    where
                       	t.nconst = %s and
                       	t.category IN ('actor', 'actress')
                    order by
                       	t2."startYear" desc nulls last,
                       	t2."primaryTitle"
                    limit 5;
                """,
                [actor_id],
            )
            actors[actor_id].played_in = [res["title"] for res in cursor]

            # Get all costars with count
            cursor.execute(
                """
                select
                   	n.primaryname as name,
                   	count(distinct costar.tconst) as anzahl
                from
                   	tprincipals tp
                   	join tmovies t
                   	on tp.tconst = t.tconst
                   	join tprincipals costar
                   	on t.tconst = costar.tconst
                   	join nbasics n
                   	on costar.nconst = n.nconst
                where
                   	tp.nconst = %s and
                   	tp.category IN ('actor', 'actress') and
                   	costar.nconst  <> %s and
                   	costar.category IN ('actor', 'actress')
                group by
                   	n.nconst
                order by
                   	anzahl desc,
                   	n.primaryname asc
                limit 5;
            """,
                [actor_id, actor_id],
            )
            actors[actor_id].costar_name_to_count = {
                rec["name"]: rec["anzahl"] for rec in cursor
            }
    return [actor for actor in actors.values()]
