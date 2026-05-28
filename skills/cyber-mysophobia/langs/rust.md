# Rust

## `use`

- Avoid `use xxx::*`, even when libraries suggest `use some_lib::prelude::*`.

## API design

- Prefer methods over free functions, with the exception of private helper functions.
	- Good:

        ```rust
        pub struct MyData { ... }
        impl MyData {
            pub fn load(...) -> MyData { ... }
        }
        ```

    - Bad:

        ```rust
        pub struct MyData { ... }
        pub fn load_data(...) -> MyData { ... }
        ```

