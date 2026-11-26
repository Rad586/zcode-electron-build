"""Defer flex item measurement constraints until a sizing path needs them."""
import argparse
from pathlib import Path

SOURCE = Path('third_party/blink/renderer/core/layout/flex/flex_layout_algorithm.cc')
START = 'void FlexLayoutAlgorithm::ConstructAndAppendFlexItems('
END = 'const LayoutResult* FlexLayoutAlgorithm::Layout()'
EAGER = '''    const auto child_space =
        BuildSpaceForLayout(child, alignment,
                            /* is_initial_block_size_indefinite */ is_column_ &&
                                !is_main_axis_inline_axis,
                            max_content_contribution);'''
LAZY = '''    std::optional<ConstraintSpace> measure_space;
    const auto MeasureSpace = [&]() -> const ConstraintSpace& {
      if (!measure_space) {
        measure_space.emplace(BuildSpaceForLayout(
            child, alignment,
            /* is_initial_block_size_indefinite */ is_column_ &&
                !is_main_axis_inline_axis,
            max_content_contribution));
      }
      return *measure_space;
    };'''
CALLS = (
    ('child.ComputeMinMaxSizes(child_writing_mode, type, child_space)',
     'child.ComputeMinMaxSizes(child_writing_mode, type, MeasureSpace())'),
    ('CalculateInitialFragmentGeometry(child_space, child,',
     'CalculateInitialFragmentGeometry(MeasureSpace(), child,'),
    ('ComputeReplacedSize(child, child_space,',
     'ComputeReplacedSize(child, MeasureSpace(),'),
    ('child.Layout(child_space)', 'child.Layout(MeasureSpace())'),
    ('table_child->ComputeCaptionBlockSize(child_space)',
     'table_child->ComputeCaptionBlockSize(MeasureSpace())'),
)


def render(text):
    start = text.index(START)
    end = text.index(END, start)
    body = text[start:end]
    if body.count('child_space') != len(CALLS) + 1:
        raise RuntimeError(f'{SOURCE.name}: unexpected measurement constraint consumers')
    for old, new in ((EAGER, LAZY), *CALLS):
        if body.count(old) != 1:
            raise RuntimeError(f'{SOURCE.name}: expected exactly one patch anchor: {old.splitlines()[0]}')
        body = body.replace(old, new)
    return text[:start] + body + text[end:]


def patch(root):
    source = root / SOURCE
    text = render(source.read_text(encoding='utf-8'))
    source.write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    patch(parser.parse_args().root)
    print('Applied lazy flex item measurement constraints.')
