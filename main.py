if __name__ == "__main__":
    try:
        from lightdiary.application import main
        raise SystemExit(main())
    except Exception:
        import sys
        if "--smoke-test" in sys.argv:
            import traceback
            from pathlib import Path
            output = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1)
        raise
