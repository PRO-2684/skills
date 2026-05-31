# Rust

## Imports

- Avoid `use xxx::*`, even when libraries suggest `use some_lib::prelude::*`; import explicit names.

## API Design

- Put type-owned behavior in `impl` blocks.
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
