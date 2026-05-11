/**
 * QuillLogo — brand mark for Quill PM.
 *
 * A stylised feather-quill pen in iOS systemBlue (#007AFF) on a white
 * rounded-square tile.  Designed to render crisply at 64 × 64 px and up.
 */

import * as React from "react";

interface QuillLogoProps {
  /** Pixel size for the outer tile (square). Default: 64 */
  size?: number;
  className?: string;
}

export function QuillLogo({ size = 64, className }: QuillLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Quill logo"
      role="img"
    >
      {/* Rounded-square tile */}
      <rect width="64" height="64" rx="14" fill="#007AFF" />

      {/*
        Feather quill — drawn as a filled path in white.
        The quill curves from the top-right tip down to a fine nib at
        bottom-left, with a subtle inner vane split.
      */}

      {/* Outer quill body */}
      <path
        d="M48 10 C48 10 54 18 50 30 C47 39 40 44 34 47 L28 54 C28 54 26 52 27 49 L30 44 C22 42 16 34 20 24 C24 14 36 10 48 10 Z"
        fill="white"
        fillOpacity="0.95"
      />

      {/* Inner vane / centre spine — slightly transparent blue for depth */}
      <path
        d="M44 14 C44 14 36 22 30 36 C28 41 28 46 28 49"
        stroke="#007AFF"
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
      />

      {/* Nib tip */}
      <path
        d="M27 49 C25 51 23 53 22 55 C24 55 26 53 28 51 Z"
        fill="white"
        fillOpacity="0.85"
      />

      {/* Small ink dot at nib */}
      <circle cx="23" cy="54" r="1.5" fill="white" fillOpacity="0.7" />
    </svg>
  );
}
