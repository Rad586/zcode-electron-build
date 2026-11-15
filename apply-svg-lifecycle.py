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
    'svg_image.cc': [
        ('#include "third_party/blink/renderer/core/paint/paint_auto_dark_mode.h"',
         '#include "third_party/blink/renderer/core/paint/paint_auto_dark_mode.h"\n'
         '#include "third_party/blink/renderer/core/paint/paint_layer.h"'),
        ('  view->UpdateAllLifecyclePhases(DocumentUpdateReason::kSVGImage);\n\n'
         '  if (RuntimeEnabledFeatures::SvgImageAnimationResetEnabled()) {',
         '  // Paint invalidation can leave the lifecycle at kPaintClean. The\n'
         '  // chrome client tracks those updates even while observers are disabled.\n'
         '  if (frame->GetDocument()->Lifecycle().GetState() !=\n'
         '          DocumentLifecycle::kPaintClean ||\n'
         '      frame->GetDocument()->NeedsLayoutTreeUpdate() ||\n'
         '      view->NeedsLayout() || chrome_client_->NeedsLifecycleUpdate() ||\n'
         '      view->GetLayoutView()->Layer()->SelfOrDescendantNeedsRepaint() ||\n'
         '      view->GetLayoutView()->NeedsPaintPropertyUpdate() ||\n'
         '      view->GetLayoutView()->DescendantNeedsPaintPropertyUpdate() ||\n'
         '      view->GetLayoutView()->ShouldCheckForPaintInvalidation() ||\n'
         '      view->GetLayoutView()->DescendantShouldCheckLayoutForPaintInvalidation() ||\n'
         '      MaybeAnimated()) {\n'
         '    chrome_client_->ClearNeedsLifecycleUpdate();\n'
         '    view->UpdateAllLifecyclePhases(DocumentUpdateReason::kSVGImage);\n'
         '  }\n\n'
         '  if (RuntimeEnabledFeatures::SvgImageAnimationResetEnabled()) {'),
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
