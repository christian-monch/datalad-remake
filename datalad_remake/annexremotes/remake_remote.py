from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)
from urllib.parse import (
    unquote,
    urlparse,
)

from datalad.customremotes import RemoteError
from datalad_next.annexremotes import SpecialRemote, super_main
from datalad_next.datasets import Dataset
from datalad_next.runners import call_git_success

from datalad_remake import (
    specification_dir,
    url_scheme,
)
from datalad_remake.commands.make_cmd import (
    execute,
    get_file_dataset,
    provide_context,
)
from datalad_remake.utils.getkeys import get_trusted_keys
from datalad_remake.utils.glob import resolve_patterns
from datalad_remake.utils.verify import verify_file

if TYPE_CHECKING:
    from collections.abc import Iterable

    from annexremote import Master

lgr = logging.getLogger('datalad.remake.annexremotes.remake')


class RemakeRemote(SpecialRemote):
    def __init__(self, annex: Master):
        super().__init__(annex)
        self.configs = {
            'allow_untrusted_execution': 'Allow execution of untrusted code with untrusted parameters. '
            'set to "true" to enable. THIS IS DANGEROUS and might lead to '
            'remote code execution.',
        }

    def __del__(self):
        self.close()

    def close(self) -> None:
        pass

    def _check_url(self, url: str) -> bool:
        return url.startswith((f'URL--{url_scheme}:', f'{url_scheme}:'))

    def prepare(self):
        self.annex.debug('PREPARE')

    def initremote(self):
        self.annex.debug('INITREMOTE')

    def remove(self, key: str):
        self.annex.debug(f'REMOVE {key!r}')

    def transfer_store(self, key: str, local_file: str):
        self.annex.debug(f'TRANSFER STORE {key!r}, {local_file!r}')

    def claimurl(self, url: str) -> bool:
        self.annex.debug(f'CLAIMURL {url!r}')
        return self._check_url(url)

    def checkurl(self, url: str) -> bool:
        self.annex.debug(f'CHECKURL {url!r}')
        return self._check_url(url)

    def getcost(self) -> int:
        self.annex.debug('GETCOST')
        return 100

    def get_url_encoded_info(self, url: str) -> list[str]:
        parts = urlparse(url).query.split('&', 5)
        self.annex.debug(f'get_url_encoded_info: url: {url!r}, parts: {parts!r}')
        return parts

    def get_url_for_key(self, key: str) -> str:
        urls = self.annex.geturls(key, f'{url_scheme}:')
        self.annex.debug(f'get_url_for_key: key: {key!r}, urls: {urls!r}')
        return urls[0]

    def get_compute_info(
        self,
        key: str,
        trusted_key_ids: list[str] | None,
    ) -> tuple[dict[str, Any], Dataset]:
        def get_assigned_value(assignment: str) -> str:
            return assignment.split('=', 1)[1]

        root_version, spec_name, this = (
            unquote(get_assigned_value(expr))
            for expr in self.get_url_encoded_info(self.get_url_for_key(key))
        )

        dataset = self._find_dataset(root_version)
        spec_path = dataset.pathobj / specification_dir / spec_name
        if trusted_key_ids is not None:
            verify_file(dataset.pathobj, spec_path, trusted_key_ids)
        with open(spec_path, 'rb') as f:
            spec = json.load(f)

        return {
            'root_version': root_version,
            'this': this,
            **{name: spec[name] for name in ['method', 'input', 'output', 'parameter']},
        }, dataset

    def transfer_retrieve(self, key: str, file_name: str) -> None:
        self.annex.debug(f'TRANSFER RETRIEVE key: {key!r}, file_name: {file_name!r}')

        if self.annex.getconfig('allow_untrusted_execution') == 'true':
            trusted_key_ids = None
        else:
            trusted_key_ids = get_trusted_keys()

        compute_info, dataset = self.get_compute_info(key, trusted_key_ids)
        self.annex.debug(f'TRANSFER RETRIEVE compute_info: {compute_info!r}')

        # Perform the computation, and collect the results
        lgr.debug('Starting provision')
        self.annex.debug('Starting provision')
        with provide_context(
            dataset, compute_info['root_version'], compute_info['input']
        ) as worktree:
            lgr.debug('Starting execution')
            self.annex.debug('Starting execution')
            execute(
                worktree,
                compute_info['method'],
                compute_info['parameter'],
                compute_info['output'],
                trusted_key_ids,
            )
            lgr.debug('Starting collection')
            self.annex.debug('Starting collection')
            self._collect(
                worktree,
                dataset,
                compute_info['output'],
                compute_info['this'],
                file_name,
            )
            lgr.debug('Leaving provision context')
            self.annex.debug('Leaving provision context')

    def checkpresent(self, key: str) -> bool:
        # See if at least one URL with the remake url-scheme is present
        return self.annex.geturls(key, f'{url_scheme}:') != []

    def _find_dataset(self, commit: str) -> Dataset:
        """Find the first enclosing dataset with the given commit"""
        # TODO: get version override from configuration
        start_dir = Path(self.annex.getgitdir()).parent.absolute()
        current_dir = start_dir
        while current_dir != Path('/'):
            result = subprocess.run(
                ['git', 'cat-file', '-t', commit],  # noqa: S607
                stdout=subprocess.PIPE,
                cwd=current_dir,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == b'commit':
                return Dataset(current_dir)
            current_dir = current_dir.parent
        msg = (
            f'Could not find dataset with commit {commit!r}, starting from '
            f'{start_dir}'
        )
        raise RemoteError(msg)

    def _collect(
        self,
        worktree: Path,
        dataset: Dataset,
        output_patterns: Iterable[str],
        this: str,
        this_destination: str,
    ) -> None:
        """Collect computation results for `this` (and all other outputs)"""

        # Get all outputs that were created during computation
        outputs = resolve_patterns(root_dir=worktree, patterns=output_patterns)

        # Collect all output files that have been created while creating
        # `this` file.
        for output in outputs:
            if output == this:
                continue
            dataset_path, file_path = get_file_dataset(dataset.pathobj / output)
            is_annexed = call_git_success(
                ['annex', 'whereis', str(file_path)],
                cwd=dataset_path,
                capture_output=True,
            )
            if is_annexed:
                self.annex.debug(
                    f'_collect: reinject: {worktree / output} -> {dataset_path}:{file_path}'
                )
                call_git_success(
                    ['annex', 'reinject', str(worktree / output), str(file_path)],
                    cwd=dataset_path,
                    capture_output=True,
                )

        # Collect `this` file. It has to be copied to the destination given
        # by git-annex. Git-annex will check its integrity.
        shutil.copyfile(worktree / this, this_destination)


def main():
    """cmdline entry point"""
    super_main(
        cls=RemakeRemote,
        remote_name='datalad-remake',
        description='Remake data based on datalad-remake specifications',
    )
