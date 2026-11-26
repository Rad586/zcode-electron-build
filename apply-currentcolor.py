"""Generate direct currentColor checks from the existing longhand metadata."""
from pathlib import Path
import sys


TEMPLATE = ('third_party/blink/renderer/build/scripts/core/css/properties/'
            'templates/css_properties.cc.tmpl')
STYLE = 'third_party/blink/renderer/core/style/computed_style.cc'
DISPATCH = '''{% if is_longhand %}
bool ComputedStyle::HasPropertyDependingOnCurrentColor() const {
{% for property in properties if property.includes_currentcolor and not property.alias_for %}
{% set name = property.name.to_upper_camel_case() %}
  if (static_cast<const css_longhand::{{name}}&>(GetCSSProperty{{name}}())
          .css_longhand::{{name}}::IsAffectedByCurrentColor(*this)) {
    return true;
  }
{% endfor %}
  return false;
}
{% endif %}

'''
EDITS = {
    TEMPLATE: [('}  // namespace {{namespace}}\n}  // namespace blink',
                '}  // namespace {{namespace}}\n\n' + DISPATCH + '}  // namespace blink')],
    STYLE: [('''bool ComputedStyle::HasPropertyDependingOnCurrentColor() const {
  for (CSSPropertyID property_id : kCSSIncludesCurrentColorProperties) {
    auto& property = CSSProperty::Get(property_id);
    DCHECK(property.IsLonghand());
    if (static_cast<const Longhand&>(property).IsAffectedByCurrentColor(
            *this)) {
      return true;
    }
  }
  return false;
}

''', '')],
}


def patch(root):
    pending = []
    for name, edits in EDITS.items():
        file = Path(root) / name
        text = file.read_text(encoding='utf-8')
        for old, new in edits:
            if text.count(old) != 1:
                raise RuntimeError(f'{name}: expected exactly one patch anchor')
            text = text.replace(old, new)
        pending.append((file, text))
    for file, text in pending:
        file.write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    patch(sys.argv[1])
    print('Applied generated direct currentColor checks.')
