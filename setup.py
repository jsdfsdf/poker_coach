from setuptools import setup, find_packages

setup(
    # The name of your package on PyPI, and how users will import it
    name="poker_coach",
    # The current version of your package
    version="0.1.0",
    # packages=["llm", "data", "engine", "coach_api", "test"],
    # List of dependencies your package requires
    packages=find_packages(),
    install_requires=["pandas>=1.0.0", "numpy", "requests", "pokerkit"],
    # Specify the minimum Python version required
    python_requires=">=3.11",
)
