from datalad.interface.base import Interface
from datalad.interface.base import build_doc as build_doc
from datalad.interface.base import eval_results as eval_results
from datalad.interface.results import get_status_dict as get_status_dict
from datalad.interface.utils import generic_result_renderer as generic_result_renderer
from datalad.support.param import Parameter as Parameter
from datalad_next.commands.results import CommandResult as CommandResult
from datalad_next.commands.results import CommandResultStatus as CommandResultStatus
from datalad_next.constraints import (
    EnsureCommandParameterization as EnsureCommandParameterization,
)
from datalad_next.constraints import (
    ParameterConstraintContext as ParameterConstraintContext,
)
from datalad_next.datasets import datasetmethod as datasetmethod

class ValidatedInterface(Interface):
    @classmethod
    def get_parameter_validator(cls) -> EnsureCommandParameterization | None: ...
