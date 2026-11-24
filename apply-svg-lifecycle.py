"""Reuse clean static SVG paint artifacts without repeating the frame lifecycle."""
from pathlib import Path
import sys


DIRECTORY = 'third_party/blink/renderer/core/svg/graphics/'
EDITS = {
    'svg_image_chrome_client.h': [
        ('  bool IsSuspended() const { return timeline_state_ >= kSuspended; }',
         '  bool IsSuspended() const { return timeline_state_ >= kSuspended; }\n\n'
         '  bool NeedsLifecycleUpdate() const { return needs_lifecycle_update_; }\n'
         '  void ClearNeedsLifecycleUpdate() { needs_lifecycle_update_ = false; }'),
        ('  SVGImage* image_;',
         '  SVGImage* image_;\n  bool needs_lifecycle_update_ = true;'),
    ],
    'svg_image_chrome_client.cc': [
        ('void SVGImageChromeClient::InvalidateContainer() {',
         'void SVGImageChromeClient::InvalidateContainer() {\n'
         '  needs_lifecycle_update_ = true;'),
        ('  DCHECK(animation_timer_);',
         '  needs_lifecycle_update_ = true;\n  DCHECK(animation_timer_);'),
    ],
    'svg_image.h': [
        ('#include "ui/gfx/geometry/size.h"',
         '#include "ui/gfx/geometry/rect.h"\n#include "ui/gfx/geometry/size.h"'),
        ('  PhysicalSize intrinsic_size_;',
         '  std::optional<PaintRecord> cached_paint_record_;\n'
         '  std::optional<gfx::Rect> cached_paint_cull_rect_;\n\n'
         '  PhysicalSize intrinsic_size_;'),
        ('  FRIEND_TEST_ALL_PREFIXES(SVGImageTest, SupportsSubsequenceCaching);',
         '  FRIEND_TEST_ALL_PREFIXES(SVGImageTest, SupportsSubsequenceCaching);\n'
         '  FRIEND_TEST_ALL_PREFIXES(SVGImageTest, ReusesPaintRecordUntilInvalidation);'),
    ],
    'svg_image.cc': [
        ('#include "third_party/blink/renderer/core/paint/paint_auto_dark_mode.h"',
         '#include "third_party/blink/renderer/core/paint/paint_auto_dark_mode.h"\n'
         '#include "third_party/blink/renderer/core/paint/paint_layer.h"'),
        ('  view->UpdateAllLifecyclePhases(DocumentUpdateReason::kSVGImage);\n\n'
         '  if (RuntimeEnabledFeatures::SvgImageAnimationResetEnabled()) {',
         '  // Paint invalidation can leave the lifecycle at kPaintClean. The\n'
         '  // chrome client tracks those updates even while observers are disabled.\n'
         '  const bool needs_lifecycle_update =\n'
         '      frame->GetDocument()->Lifecycle().GetState() !=\n'
         '          DocumentLifecycle::kPaintClean ||\n'
         '      frame->GetDocument()->NeedsLayoutTreeUpdate() ||\n'
         '      view->NeedsLayout() || chrome_client_->NeedsLifecycleUpdate() ||\n'
         '      view->GetLayoutView()->Layer()->SelfOrDescendantNeedsRepaint() ||\n'
         '      view->GetLayoutView()->NeedsPaintPropertyUpdate() ||\n'
         '      view->GetLayoutView()->DescendantNeedsPaintPropertyUpdate() ||\n'
         '      view->GetLayoutView()->ShouldCheckForPaintInvalidation() ||\n'
         '      view->GetLayoutView()->DescendantShouldCheckLayoutForPaintInvalidation() ||\n'
         '      MaybeAnimated();\n'
         '  if (needs_lifecycle_update) {\n'
         '    cached_paint_record_.reset();\n'
         '    chrome_client_->ClearNeedsLifecycleUpdate();\n'
         '    view->UpdateAllLifecyclePhases(DocumentUpdateReason::kSVGImage);\n'
         '  }\n\n'
         '  if (RuntimeEnabledFeatures::SvgImageAnimationResetEnabled()) {'),
        ('  return view->GetPaintRecord(cull_rect);',
         '  // Only retain records once a draw repeats without lifecycle work.\n'
         '  // Animated and changing-container draws use the transient result.\n'
         '  if (needs_lifecycle_update) {\n'
         '    return view->GetPaintRecord(cull_rect);\n'
         '  }\n'
         '  const std::optional<gfx::Rect> requested_cull_rect =\n'
         '      cull_rect ? std::make_optional(*cull_rect) : std::nullopt;\n'
         '  if (!cached_paint_record_ ||\n'
         '      cached_paint_cull_rect_ != requested_cull_rect) {\n'
         '    cached_paint_record_ = view->GetPaintRecord(cull_rect);\n'
         '    cached_paint_cull_rect_ = requested_cull_rect;\n'
         '  }\n'
         '  return *cached_paint_record_;'),
    ],
}

TESTS = r'''class SVGImageLifecycleCounter final
    : public GarbageCollected<SVGImageLifecycleCounter>,
      public LocalFrameView::LifecycleNotificationObserver {
 public:
  void WillStartLifecycleUpdate(const LocalFrameView&) override { ++count; }
  unsigned count = 0;
};

TEST_F(SVGImageTest, ReusesStaticPaintWithoutLifecycle) {
  Load(base::span_from_cstring(
           "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'>"
           "<rect width='100' height='100' fill='red'/></svg>"), true);
  PumpFrame();
  auto* frame = To<LocalFrame>(GetImage().GetPageForTesting()->MainFrame());
  auto* counter = MakeGarbageCollected<SVGImageLifecycleCounter>();
  frame->View()->RegisterForLifecycleNotifications(counter);
  PumpFrame();
  PumpFrame();
  EXPECT_EQ(counter->count, 0u);

  frame->View()->GetLayoutView()->Layer()->SetNeedsRepaint();
  PumpFrame();
  EXPECT_EQ(counter->count, 1u);
  PumpFrame();
  EXPECT_EQ(counter->count, 1u);
  frame->View()->UnregisterFromLifecycleNotifications(counter);
}

TEST_F(SVGImageTest, ReusesPaintRecordUntilInvalidation) {
  Load(base::span_from_cstring(
           "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'>"
           "<rect width='100%' height='100%' fill='red'/></svg>"), true);
  const SVGImage::DrawInfo info(gfx::SizeF(100, 100), 1, nullptr, false);
  const gfx::Vector2dF scale(1, 1);
  const gfx::Rect full(100, 100);
  auto initial = GetImage().PaintRecordForCurrentFrame(info, scale, &full);
  ASSERT_TRUE(initial);
  EXPECT_FALSE(GetImage().cached_paint_record_);
  auto first = GetImage().PaintRecordForCurrentFrame(info, scale, &full);
  ASSERT_TRUE(first);
  auto repeated = GetImage().PaintRecordForCurrentFrame(info, scale, &full);
  ASSERT_TRUE(repeated);
  EXPECT_EQ(&first->buffer(), &repeated->buffer());

  const gfx::Rect clipped(50, 50);
  auto cropped = GetImage().PaintRecordForCurrentFrame(info, scale, &clipped);
  ASSERT_TRUE(cropped);
  EXPECT_NE(&first->buffer(), &cropped->buffer());
  auto uncropped = GetImage().PaintRecordForCurrentFrame(info, scale, nullptr);
  ASSERT_TRUE(uncropped);
  EXPECT_NE(&cropped->buffer(), &uncropped->buffer());
  auto uncropped_again =
      GetImage().PaintRecordForCurrentFrame(info, scale, nullptr);
  ASSERT_TRUE(uncropped_again);
  EXPECT_EQ(&uncropped->buffer(), &uncropped_again->buffer());

  auto* frame = To<LocalFrame>(GetImage().GetPageForTesting()->MainFrame());
  frame->View()->GetLayoutView()->Layer()->SetNeedsRepaint();
  auto repainted = GetImage().PaintRecordForCurrentFrame(info, scale, nullptr);
  ASSERT_TRUE(repainted);
  EXPECT_NE(&uncropped->buffer(), &repainted->buffer());
  EXPECT_FALSE(GetImage().cached_paint_record_);
  auto clean = GetImage().PaintRecordForCurrentFrame(info, scale, nullptr);
  ASSERT_TRUE(clean);
  EXPECT_TRUE(GetImage().cached_paint_record_);
  auto clean_again = GetImage().PaintRecordForCurrentFrame(info, scale, nullptr);
  ASSERT_TRUE(clean_again);
  EXPECT_EQ(&clean->buffer(), &clean_again->buffer());

  const SVGImage::DrawInfo resized_info(gfx::SizeF(50, 50), 1, nullptr, false);
  auto resized =
      GetImage().PaintRecordForCurrentFrame(resized_info, scale, nullptr);
  ASSERT_TRUE(resized);
  EXPECT_NE(&repainted->buffer(), &resized->buffer());
  EXPECT_FALSE(GetImage().cached_paint_record_);
  const gfx::Vector2dF changed_scale(2, 2);
  auto scaled = GetImage().PaintRecordForCurrentFrame(
      resized_info, changed_scale, nullptr);
  ASSERT_TRUE(scaled);
  EXPECT_NE(&resized->buffer(), &scaled->buffer());
  EXPECT_FALSE(GetImage().cached_paint_record_);
}

TEST_F(SVGImageTest, AnimatedPaintStillUpdatesLifecycle) {
  Load(base::span_from_cstring(kAnimatedDocument), false);
  PumpFrame();
  auto* frame = To<LocalFrame>(GetImage().GetPageForTesting()->MainFrame());
  auto* counter = MakeGarbageCollected<SVGImageLifecycleCounter>();
  frame->View()->RegisterForLifecycleNotifications(counter);
  PumpFrame();
  EXPECT_GT(counter->count, 0u);
  frame->View()->UnregisterFromLifecycleNotifications(counter);
}

'''
EDITS['svg_image_test.cc'] = [
    ('TEST_F(SVGImageTest, SupportsSubsequenceCaching) {',
     TESTS + 'TEST_F(SVGImageTest, SupportsSubsequenceCaching) {'),
]


def patch(root):
    pending = []
    for name, edits in EDITS.items():
        file = Path(root) / DIRECTORY / name
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
    print('Applied static SVG lifecycle reuse.')
