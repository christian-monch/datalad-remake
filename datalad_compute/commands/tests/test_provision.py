from __future__ import annotations

import contextlib
from contextlib import chdir, contextmanager
from pathlib import Path
from typing import Iterable

from datalad_next.datasets import Dataset
from datalad_next.runners import call_git_lines

from .create_datasets import create_ds_hierarchy
from ..compute_cmd import provide_context


file_path_templates = [
    '{file}.txt',
    '{{ds_name}}_subds0/{file}0.txt',
    '{{ds_name}}_subds0/{{ds_name}}_subds1/{file}1.txt',
    '{{ds_name}}_subds0/{{ds_name}}_subds1/{{ds_name}}_subds2/{file}2.txt',
]


all_paths = [
    template.format(file=f)
    for template in file_path_templates
    for f in ['a', 'b']
]

a_paths = [
    path.format(file='a')
    for path in file_path_templates
]

b_paths = [
    path.format(file='b')
    for path in file_path_templates
]


def test_worktree_basic(tmp_path):
    dataset = create_ds_hierarchy(tmp_path, 'ds1', 3)[0][2]
    inputs = [
        'a.txt', 'b.txt',
        'ds1_subds0/a0.txt', 'ds1_subds0/b0.txt',
        'ds1_subds0/ds1_subds1/a1.txt', 'ds1_subds0/ds1_subds1/b1.txt'
    ]
    provision_result = dataset.provision(
        worktree_dir=tmp_path / 'ds1_worktree1',
        input=inputs,
    )[0]

    worktree = Dataset(provision_result['path'])
    # Check input availability
    assert all((worktree.pathobj / path).exists() for path in inputs)

    dataset.provision(delete=worktree.path)

    def check_deleted_worktrees(ds: Dataset):
        with chdir(ds.path):
            for line in call_git_lines(['worktree', 'list']):
                directory = line.split()[0]
                assert directory == ds.path
        for sub_ds in ds.subdatasets(result_renderer='disabled'):
            check_deleted_worktrees(Dataset(sub_ds['path']))

    check_deleted_worktrees(dataset)
    dataset.drop(
        what='all',
        reckless='kill',
        recursive=True,
        result_renderer='disabled')


def test_worktree_globbing(tmp_path):
    dataset = create_ds_hierarchy(tmp_path, 'ds1', 3)[0][2]
    result = dataset.provision(
        worktree_dir=tmp_path / 'ds1_worktree2',
        input=[
            '*.txt',
            '*_subds0/*.txt',
            '*_subds0/*_subds1/*.txt',
            '*_subds0/*_subds1/*_subds2/*.txt',
        ],
    )[0]

    worktree = Path(result['path'])
    worktree_set = set(get_file_list(worktree))
    assert worktree_set == set(
        path.format(ds_name='ds1')
        for path in all_paths
    )
    dataset.provision(delete=worktree)

    result = dataset.provision(
        worktree_dir=tmp_path / 'ds1_worktree2',
        input=[
            'b*txt',
            '*_subds0/b*txt',
            '*_subds0/*_subds1/b*txt',
            '*_subds0/*_subds1/*_subds2/b*txt',
        ],
    )[0]

    worktree = Path(result['path'])
    worktree_set = set(get_file_list(worktree))
    assert set(
        path.format(ds_name='ds1')
        for path in b_paths
    ).issubset(worktree_set)
    dataset.provision(delete=worktree)

    dataset.drop(
        what='all',
        reckless='kill',
        recursive=True,
        result_renderer='disabled')


def get_file_list(root: Path,
                  path: Path|None = None,
                  prefix: Path|None = None
                  ) -> Iterable[str]:
    prefix = prefix or Path('')
    path = path or root
    for child in path.iterdir():
        if not child.name.startswith('.'):
            if child.is_dir():
                yield from get_file_list(root, child, prefix=prefix / child)
            else:
                yield str((prefix / child).relative_to(root))


def test_provision_context(tmp_path):
    dataset = create_ds_hierarchy(tmp_path, 'ds1')[0][2]
    with provide_context(dataset, branch=None, input_patterns=['**']) as worktree:
        files = set(get_file_list(worktree))
        assert files
    assert not worktree.exists()


def test_unclean_dataset(tmp_path):
    dataset = Dataset(tmp_path / 'ds1')
    dataset.create(cfg_proc='text2git', result_renderer='disabled')
    (dataset.pathobj / 'a.txt').write_text('content')
    dataset.save()
    (dataset.pathobj / 'a.txt').write_text('changed content')
    (dataset.pathobj / 'b.txt').write_text('untracked content')

    # Check that provision of unclean input results in errors
    input_pattern = ['a.txt', 'b.txt']
    results = dataset.provision(
        input=input_pattern,
        worktree_dir=tmp_path / 'ds1_worktree1',
        on_failure='ignore')
    assert set((result['status'], result['state']) for result in results) == \
        {('error', 'modified'), ('error', 'untracked')}

    # Check that a saved dataset can be provisioned
    dataset.save()
    dataset.provision(
        input=input_pattern,
        worktree_dir=tmp_path / 'ds1_worktree2')

    # Check that non-input file `c.txt` is ignored
    (dataset.pathobj / 'c.txt').write_text('content')
    dataset.provision(
        input=input_pattern,
        worktree_dir=tmp_path / 'ds1_worktree3')


def test_branch_deletion_after_provision(tmp_path):
    dataset = create_ds_hierarchy(tmp_path, 'ds1', 3)[0][2]
    with provide_context(
            dataset=dataset,
            branch=None,
            input_patterns=['a.txt']
    ) as worktree:
        assert worktree.exists()
    assert not worktree.exists()
    with contextlib.chdir(dataset.path):
        branches = [
            l.strip()
            for l in call_git_lines(['branch'])]
    assert worktree.name not in branches
