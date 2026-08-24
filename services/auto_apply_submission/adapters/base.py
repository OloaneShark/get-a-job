class SubmissionAdapter:
    adapter_name = "base"

    def submit(
        self,
        job,
        identity,
        application_email,
        resume_path,
        cover_letter_text=None,
        resume_mode=False,
        application_answers=None,
    ):
        raise NotImplementedError
