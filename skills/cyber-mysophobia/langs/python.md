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

## API design

- Prefer methods over free functions
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

