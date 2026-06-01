"""Aggregator of all Quill PMO sub-agents."""
from .comms_drafter.agent import agent as comms_drafter
from .coordinator.agent import agent as coordinator
from .daily_brief.agent import agent as daily_brief
from .design_classifier.agent import agent as design_classifier
from .estimator_scheduler.agent import agent as estimator_scheduler
from .knowledge_manager.agent import agent as knowledge_manager
from .procurement_watch.agent import agent as procurement_watch
from .project_coordinator.agent import agent as project_coordinator
from .project_manager.agent import agent as project_manager
from .rfi_drafter.agent import agent as rfi_drafter
from .rfi_triage.agent import agent as rfi_triage
from .status_update_author.agent import agent as status_update_author
from .submittal_spec_validator.agent import agent as submittal_spec_validator
from .submittal_triage.agent import agent as submittal_triage
from .contract_drafter.agent import agent as contract_drafter
from .contract_extractor.agent import agent as contract_extractor
from .contract_interpreter.agent import agent as contract_interpreter
from .contract_reviewer.agent import agent as contract_reviewer
from .ccb_prep.agent import agent as ccb_prep
from .co_estimator.agent import agent as co_estimator
from .critical_path_watch.agent import agent as critical_path_watch
from .dfr_synthesizer.agent import agent as dfr_synthesizer
from .owner_reporting.agent import agent as owner_reporting
from .progress_capture.agent import agent as progress_capture
from .safety_aggregator.agent import agent as safety_aggregator
from .schedule_reader.agent import agent as schedule_reader
from .request_intake.agent import agent as request_intake

ALL_SUB_AGENTS = [
    comms_drafter,
    coordinator,
    daily_brief,
    design_classifier,
    estimator_scheduler,
    knowledge_manager,
    procurement_watch,
    project_coordinator,
    project_manager,
    rfi_drafter,
    rfi_triage,
    status_update_author,
    submittal_spec_validator,
    submittal_triage,
    contract_drafter,
    contract_extractor,
    contract_interpreter,
    contract_reviewer,
    ccb_prep,
    co_estimator,
    critical_path_watch,
    dfr_synthesizer,
    owner_reporting,
    progress_capture,
    safety_aggregator,
    schedule_reader,
    request_intake,
]
