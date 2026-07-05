import { domToPng } from "modern-screenshot"

/**
 * Capture the rendered page canvas as a base64 PNG for visual-feedback refinement.
 * `targetWidth` (the attached design's pixel width) scales the capture so the render and the
 * design reach the model at comparable resolution — otherwise it "fixes" differences that are
 * just resolution mismatch.
 */
export async function captureRenderedPage(targetWidth?: number): Promise<string | null> {
	const canvases = Array.from(document.querySelectorAll<HTMLElement>(".canvas"))
	if (!canvases.length) return null
	// Multiple canvases can exist (breakpoint previews) — capture the widest (desktop).
	const target = canvases.reduce((widest, el) => (el.offsetWidth > widest.offsetWidth ? el : widest))
	const width = target.offsetWidth || 1200
	const scale = clamp((targetWidth || 1200) / width, 0.5, 1.5)

	// The editor pans/zooms the canvas via a CSS transform (scale + translate) on its wrapper,
	// and modern-screenshot measures the node with getBoundingClientRect() — which is transformed,
	// so a zoomed-out canvas captures clipped and offset. Neutralize the transform for the capture
	// and restore it after (Vue's :style binding re-applies it on the next render regardless).
	const wrapper = target.parentElement
	const savedTransform = wrapper?.style.transform ?? ""
	if (wrapper) wrapper.style.transform = "none"
	try {
		return await domToPng(target, { backgroundColor: "#ffffff", scale })
	} catch (error) {
		console.error("Failed to capture the rendered page", error)
		return null
	} finally {
		if (wrapper) wrapper.style.transform = savedTransform
	}
}

/** Pixel width of an image data URL — used to match the capture scale to the design. */
export function getImageWidth(dataUrl: string): Promise<number | null> {
	return new Promise((resolve) => {
		const img = new Image()
		img.onload = () => resolve(img.naturalWidth || null)
		img.onerror = () => resolve(null)
		img.src = dataUrl
	})
}

function clamp(value: number, min: number, max: number): number {
	return Math.min(Math.max(value, min), max)
}