"""Skip external SVG scale invalidation until the root transform uses that scale."""
from pathlib import Path
import sys

DIRECTORY = 'third_party/blink/renderer/core/'
TESTS = r'''TEST_F(SVGImageTest, ContainerScaleInvalidatesOnlyAfterTransformUsesIt) {
  Load(base::span_from_cstring(
           "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'>"
           "<rect id='shape' width='80' height='80' stroke='blue'/>"
           "</svg>"),
       true);
  PumpFrame();
  auto* frame = To<LocalFrame>(GetImage().GetPageForTesting()->MainFrame());
  auto* view = frame->View();
  const unsigned initial_layouts = view->LayoutCountForTesting();
  PumpFrame(gfx::RectF(0, 0, 200, 300));
  PumpFrame(gfx::RectF(0, 0, 300, 200));
  EXPECT_EQ(initial_layouts, view->LayoutCountForTesting());

  Element* shape = frame->GetDocument()->getElementById(AtomicString("shape"));
  ASSERT_TRUE(shape);
  shape->setAttribute(svg_names::kVectorEffectAttr,
                      AtomicString("non-scaling-stroke"));
  PumpFrame(gfx::RectF(0, 0, 300, 200));
  auto* layout_shape = To<LayoutSVGShape>(shape->GetLayoutObject());
  ASSERT_TRUE(layout_shape);
  ASSERT_TRUE(layout_shape->HasNonScalingStroke());
  EXPECT_DOUBLE_EQ(3, layout_shape->NonScalingStrokeTransform().A());
  EXPECT_DOUBLE_EQ(2, layout_shape->NonScalingStrokeTransform().D());

  const unsigned stroke_layouts = view->LayoutCountForTesting();
  PumpFrame(gfx::RectF(0, 0, 400, 500));
  EXPECT_GT(view->LayoutCountForTesting(), stroke_layouts);
  EXPECT_DOUBLE_EQ(4, layout_shape->NonScalingStrokeTransform().A());
  EXPECT_DOUBLE_EQ(5, layout_shape->NonScalingStrokeTransform().D());

  auto* root = frame->GetDocument()->documentElement();
  shape->remove();
  PumpFrame(gfx::RectF(0, 0, 500, 400));
  ASSERT_FALSE(shape->GetLayoutObject());
  root->AppendChild(shape);
  PumpFrame(gfx::RectF(0, 0, 500, 400));
  layout_shape = To<LayoutSVGShape>(shape->GetLayoutObject());
  ASSERT_TRUE(layout_shape);
  ASSERT_TRUE(layout_shape->HasNonScalingStroke());
  EXPECT_DOUBLE_EQ(5, layout_shape->NonScalingStrokeTransform().A());
  EXPECT_DOUBLE_EQ(4, layout_shape->NonScalingStrokeTransform().D());
}

TEST_F(SVGImageTest, ContainerScaleInvalidatesAfterOrdinaryStrokeHitTest) {
  Load(base::span_from_cstring(
           "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'>"
           "<path id='shape' d='M10 50 C30 10 70 10 90 50' fill='none' "
           "stroke='blue' stroke-width='8' pointer-events='stroke'/>"
           "</svg>"),
       true);
  PumpFrame(gfx::RectF(0, 0, 200, 300));
  auto* frame = To<LocalFrame>(GetImage().GetPageForTesting()->MainFrame());
  auto* view = frame->View();
  auto* document = frame->GetDocument();
  auto* shape = document->getElementById(AtomicString("shape"));
  ASSERT_TRUE(shape);
  const auto* root =
      To<LayoutSVGRoot>(document->documentElement()->GetLayoutObject());
  ASSERT_TRUE(root);
  const auto hit_test = [root](float y) {
    const HitTestLocation location(gfx::PointF(50, y));
    HitTestResult result(HitTestRequest(HitTestRequest::kReadOnly), location);
    root->IntersectChildren(result, location);
    return result.InnerNode();
  };

  const unsigned initial_layouts = view->LayoutCountForTesting();
  PumpFrame(gfx::RectF(0, 0, 300, 200));
  EXPECT_EQ(initial_layouts, view->LayoutCountForTesting());
  ASSERT_EQ(shape, hit_test(20));
  EXPECT_NE(shape, hit_test(40));

  const unsigned hit_test_layouts = view->LayoutCountForTesting();
  PumpFrame(gfx::RectF(0, 0, 400, 500));
  EXPECT_GT(view->LayoutCountForTesting(), hit_test_layouts);
  EXPECT_EQ(shape, hit_test(20));
  EXPECT_NE(shape, hit_test(40));
}

'''
EDITS = {
    'layout/svg/layout_svg_root.h': [
        ('    if (container_scale_ != container_scale) {',
         '    if (container_scale_used_ && container_scale_ != container_scale) {'),
        ('  const gfx::Vector2dF& GetContainerScale() const {\n'
         '    NOT_DESTROYED();\n'
         '    return container_scale_;\n'
         '  }',
         '  const gfx::Vector2dF& ContainerScaleForTransform() const {\n'
         '    NOT_DESTROYED();\n'
         '    // Once a transform depends on the scale, cached layout or stroke\n'
         '    // data may still use it until the next invalidation.\n'
         '    container_scale_used_ = true;\n'
         '    return container_scale_;\n'
         '  }'),
        ('  bool container_scale_changed_ : 1;',
         '  bool container_scale_changed_ : 1;\n'
         '  mutable bool container_scale_used_ : 1 = false;'),
    ],
    'layout/svg/layout_svg_shape.cc': [
        ('    const gfx::Vector2dF& scale = layout_svg_root->GetContainerScale();',
         '    const gfx::Vector2dF& scale =\n'
         '        layout_svg_root->ContainerScaleForTransform();'),
    ],
    'svg/graphics/svg_image_test.cc': [
        ('#include "third_party/blink/renderer/core/frame/local_dom_window.h"',
         '#include "third_party/blink/renderer/core/dom/document.h"\n'
         '#include "third_party/blink/renderer/core/frame/local_dom_window.h"'),
        ('#include "third_party/blink/renderer/core/layout/layout_shift_tracker.h"',
         '#include "third_party/blink/renderer/core/layout/hit_test_location.h"\n'
         '#include "third_party/blink/renderer/core/layout/hit_test_result.h"\n'
         '#include "third_party/blink/renderer/core/layout/layout_shift_tracker.h"'),
        ('#include "third_party/blink/renderer/core/layout/layout_view.h"',
         '#include "third_party/blink/renderer/core/layout/layout_view.h"\n'
         '#include "third_party/blink/renderer/core/layout/svg/layout_svg_root.h"\n'
         '#include "third_party/blink/renderer/core/layout/svg/layout_svg_shape.h"'),
        ('  void PumpFrame() {',
         '  void PumpFrame(const gfx::RectF& destination = gfx::RectF(0, 0, 100, 100)) {'),
        ('    image->Draw(&canvas, flags, dummy_rect, dummy_rect, ImageDrawOptions());',
         '    image->Draw(&canvas, flags, destination, dummy_rect, ImageDrawOptions());'),
        ('#include "third_party/blink/renderer/core/svg/svg_svg_element.h"',
         '#include "third_party/blink/renderer/core/svg/svg_svg_element.h"\n'
         '#include "third_party/blink/renderer/core/svg_names.h"'),
        ('TEST_F(SVGImageTest, LayoutShiftTrackerDisabled) {',
         TESTS + 'TEST_F(SVGImageTest, LayoutShiftTrackerDisabled) {'),
    ],
}
TEST_FILE = 'svg/graphics/svg_image_test.cc'
CACHE_TEST = 'TEST_F(SVGImageTest, ReusesPaintRecordUntilInvalidation) {'


def patch(root):
    pending = {}
    for name, edits in EDITS.items():
        file = Path(root) / DIRECTORY / name
        text = file.read_text(encoding='utf-8')
        if name == TEST_FILE and CACHE_TEST in text:
            raise RuntimeError('SVG scale experiment requires the static-only lifecycle patch')
        for old, new in edits:
            if text.count(old) != 1:
                raise RuntimeError(f'{name}: expected exactly one patch anchor')
            text = text.replace(old, new)
        pending[file] = text
    for file, text in pending.items():
        file.write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    patch(sys.argv[1])
    print('Applied SVG transform-dependent scale invalidation.')
