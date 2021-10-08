# ----------------------------------------------------------------------------
# Copyright (c) 2016-2021, QIIME 2 development team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------


import contextlib
import qiime2.sdk.usage as usage


def write_example_data(action, output_dir):
    import os
    import qiime2.sdk.usage as usage
    import qiime2.util as util

    os.makedirs(output_dir, exist_ok=True)

    # TODO: looks like something might be wrong here still?

    use = usage.NoOpUsage()
    scope = usage.Scope()
    with use.bind(scope):
        for example in action.examples:
            example(use)

    for record in scope:
        path = os.path.join(output_dir, record.name)
        data = record.factory()
        if str(type(data)) == 'Artifact' or str(type(data)) == 'Visualization':
            path = data.save(path)
            hint = repr(data.type)
        # elif record.type == 'metadata':
        #     path += '.tsv'
        #     data.save(path)
        #     hint = 'Metadata'
        # elif record.type == 'file':
        #     util.duplicate(data, path)
        #     hint = 'file'
        else:
            raise NotImplementedError

        yield hint, path


def write_plugin_example_data(plugin, output_dir):
    import os
    import q2cli.util

    for name, action in plugin.actions.items():
        path = os.path.join(output_dir, q2cli.util.to_cli_name(name))
        os.makedirs(output_dir, exist_ok=True)

        yield from write_example_data(action, path)


class CLIUsageFormatter(usage.Usage):
    def __init__(self, outdir=None, test=True):
        super().__init__()
        self.outdir = outdir
        self._outdir_map = {}
        self.test = test
        self._lines = []

    def get_result(self):
        return self._lines

    @contextlib.contextmanager
    def settings(self, outdir=None, test=None):
        if outdir is not None:
            backup_outdir, self.outdir = self.outdir, outdir
        if test is not None:
            backup_test, self.test = self.test, test
        try:
            yield
        finally:
            self.outdir = backup_outdir
            self.test = backup_test

    def _dereference(self, input_name):
        record = self.scope[input_name]
        result = record.factory()

        if record.type == 'file':
            return input_name
        elif record.type == 'metadata':
            return input_name + '.tsv'

        prefix = self._outdir_map.get(input_name, '')
        if record.type == 'artifact':
            suffix = '.qza'
        else:
            suffix = '.qzv'

        return prefix + input_name + suffix

    def _store_outputs(self, action):
        outdir = None
        outputs = {}

        if len(action.signature.outputs) > 4:
            outdir = to_cli_name(action.id) + '-results/'
        if self.outdir is not None:
            outdir = self.outdir

        full_outputs = {k: k for k in action.signature.outputs}
        full_outputs.update(outputs)

        for original_name, save_name in full_outputs.items():
            spec = action.signature.outputs[original_name]
            if spec.qiime_type.name == 'Visualization':
                self._scope.add_visualization(save_name, None)
            else:
                self._scope.push_record(save_name, False, value=None)

        if outdir is not None:
            for save_name in full_outputs.values():
                self._outdir_map[save_name] = outdir

        return full_outputs, outdir

    def _get_plugin_name(self, action):
        return action.plugin_id

    def _make_param(self, value, state):
        import shlex
        import q2cli.click.option

        state = state.copy()
        type_ = state.pop('type')

        opt = q2cli.click.option.GeneratedOption(prefix=type_[0], **state)
        option = opt.opts[0]
        if state['metadata'] == 'file':
            if type(value) is str:
                return [(option, shlex.quote(self._dereference(value)))]
            else:
                value = [shlex.quote(self._dereference(v)) for v in value]
                return [(option, ' '.join(value))]

        if state['metadata'] == 'column':
            value, column = value
            return [(option, shlex.quote(self._dereference(value))),
                    (opt.q2_extra_opts[0], shlex.quote(column))]

        if type_ != 'parameter':
            if state['multiple'] is None:
                return [(option, shlex.quote(self._dereference(value)))]
            else:
                value = [shlex.quote(self._dereference(v)) for v in value]
                return [(option, ' '.join(value))]
        else:
            if type(value) is bool:
                if value:
                    return [(option, None)]
                else:
                    return [(opt.secondary_opts[0], None)]
            if type(value) is str:
                return [(option, shlex.quote(value))]
            else:
                return [(option, str(value))]

    def action(self, action, inputs, outputs=None):
        import shlex
        from q2cli.util import to_cli_name
        from q2cli.core.state import get_action_state

        INDENT = ' ' * 2
        action_f = action.get_action(self._plugin_manager)
        full_outputs, outdir = self._store_outputs(action_f)

        action_state = get_action_state(action_f)
        input_signature = {s['name']: s for s in action_state['signature']
                           if s['type'] != 'output'}
        output_signature = {s['name']: s for s in action_state['signature']
                            if s['type'] == 'output'}

        plugin_name = to_cli_name(self._get_plugin_name(action))
        action_name = to_cli_name(action_f.id)
        self._lines.append('qiime %s %s \\' % (plugin_name, action_name))

        for param_name, value in inputs.items():
            param_state = input_signature[param_name]
            for opt, val in self._make_param(value, param_state):
                line = INDENT + opt
                if val is not None:
                    line += ' ' + val
                line += ' \\'

                self._lines.append(line)

        if outdir is not None:
            self._lines.append(
                INDENT + '--output-dir %s' % shlex.quote(outdir))
        else:
            for param_name, value in full_outputs.items():
                param_state = output_signature[param_name]
                for opt, val in self._make_param(value, param_state):
                    line = INDENT + opt
                    if val is not None:
                        line += ' ' + val
                    line += ' \\'

                    self._lines.append(line)
            self._lines[-1] = self._lines[-1][:-2]  # remove trailing \

    def comment(self, text):
        import textwrap
        self._lines += ['# ' + line for line in textwrap.wrap(text, width=74)]

    def import_file(self, type, input_name, output_name=None, format=None):
        'qiime tools import '
        pass

    def export_file(self, input_name, output_name, format=None):
        'qiime tools export '
        pass

    def _assert_has_line_matching_(self, label, result, path, expression):
        pass
