import marimo

__generated_with = "0.24.2"
app = marimo.App()


@app.cell
def _():
    import marimo
    import pandas as pd

    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Testing this
    """)
    return


if __name__ == "__main__":
    app.run()
