# Python

## Dynamic Attr

- Use direct attributes when contract says field exists: `obj.attribute`.
- Avoid `getattr` unless attribute truly optional, dynamic, or external.
- Do not use `getattr(obj, "x", default)` to hide bad model/API design. Fix contract.

## Path Manipulation

- Avoid `sys.path` insertion unless no packaging/test config fix works.
- Do not add project-root injection like:

    ```python
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    ```

- Prefer proper package layout, editable install, test runner config, or `PYTHONPATH` set by tooling.
- If path insertion unavoidable, isolate it, comment exact reason, and remove once packaging fixed.

## Imports

- Avoid `from module import *`; import explicit names.
- Avoid import checking (`try: import xxx`), if the environment spec already requires the library.
- Avoid `__import__` or `importlib` - use `import xxx` directly.
- Keep imports at the beginning.

## Typing

- Avoid `Any`.

## API Design

- Put type-owned behavior on the type via `@staticmethod` or `@classmethod` unless a private helper is clearer.
    - Good:

        ```python
        class MyData:
            @staticmethod
            def load(...) -> Self:
                ...
            # classmethod is also accepted
        ```

    - Bad:

        ```python
        class MyData:
            ...
        def load_data(...) -> MyData:
            ...
        ```

- Prefer typed over untyped.
    - Good: Use `dataclass`, `TypedDict`, pydantic or others to type data (choose the method that fits best):

        ```python
        @dataclass
        class Entry:
            id: str
            data: list[int]
        # ...
        return Entry(...)
        ```

    - Bad: Use untyped dict / object:

        ```python
        return { "id": ..., "data": ... }
        ```

- Prefer explicit over implicit.
