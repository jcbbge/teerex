"""Restore the board's width through Rex's documented layout/border API."""
import json
import os
import subprocess


def leaf(node):
    return node.get('block_id') or leaf(node['split']['before'])


def border(node, block):
    if node.get('block_id') == block:
        return []
    split = node.get('split')
    if not split:
        return None
    for side in ('before', 'after'):
        path = border(split[side], block)
        if path is not None:
            return [(node, side)] + path
    return None


def restore(rex, session, block):
    def rpc(method, args):
        return json.loads(subprocess.check_output(rex + ['api', 'call', method, json.dumps(args)], stderr=subprocess.DEVNULL, timeout=3))
    view = rpc('session.view', {'session_id': session})
    for window in view.get('windows') or []:
        for layer in window.get('layers') or []:
            if layer.get('kind') != 'tiled' or not layer.get('layout'):
                continue
            path = border(layer['layout'], block)
            if path is None:
                continue
            for node, side in reversed(path):
                split = node['split']
                if split['direction'] != 'horizontal' or node['rect'][2] <= 1 / 3:
                    continue
                fraction = (1 / 3) / node['rect'][2]
                ratio = fraction if side == 'before' else 1 - fraction
                if abs(split['ratio'] - ratio) > .001:
                    rpc('session.resize_pane', dict(session_id=session, direction='horizontal', before_block_id=leaf(split['before']), after_block_id=leaf(split['after']), ratio=ratio))
                return


if __name__ == '__main__':
    session = os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION')
    block = os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK')
    if session and block:
        rex = [os.environ.get('TEEREX_INTERNAL_REX', os.environ.get('REX_BIN', 'rex')), '--autostart=false']
        endpoint = os.environ.get('REX_SERVER')
        if endpoint:
            rex += ['--server', endpoint]
        try:
            restore(rex, session, block)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
