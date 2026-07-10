"""Chart generation service for AI analysis responses."""

from __future__ import annotations

import base64
import io
from typing import Any

import matplotlib.pyplot as plt
import matplotlib
from matplotlib.figure import Figure

# Use non-interactive backend for server-side chart generation
matplotlib.use('Agg')

# Set style for dark theme compatibility
plt.style.use('dark_background')


class ChartGenerator:
    """Generate chart images for AI analysis responses."""

    def __init__(self):
        """Initialize chart generator with default styling."""
        # Brand colors matching frontend
        self.colors = {
            'emerald': '#059669',
            'emerald_dark': '#064e3b',
            'red': '#ef4444',
            'grid': '#27272a',
            'muted': '#52525b',
            'bg': '#09090b',
        }

    def generate_bar_chart(
        self,
        data: list[dict[str, Any]],
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        width: int = 800,
        height: int = 400,
    ) -> str:
        """Generate a bar chart and return base64-encoded image.

        Args:
            data: List of dicts with 'label' and 'value' keys
            title: Chart title
            xlabel: X-axis label
            ylabel: Y-axis label
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            Base64-encoded PNG image string
        """
        fig, ax = plt.subplots(figsize=(width/100, height/100))
        
        labels = [item.get('label', '') for item in data]
        values = [item.get('value', 0) for item in data]
        colors = [
            item.get('color', self.colors['emerald'] if v >= 0 else self.colors['red'])
            for v in values
        ]

        bars = ax.bar(labels, values, color=colors)
        
        # Add value labels on bars
        for bar, value in zip(bars, values):
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2.,
                height,
                f'{value:.1f}%',
                ha='center',
                va='bottom' if height >= 0 else 'top',
                fontsize=9,
            )

        ax.set_title(title, fontsize=12, fontweight='bold', pad=10)
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(True, alpha=0.3, axis='y')
        ax.set_facecolor(self.colors['bg'])
        fig.patch.set_facecolor(self.colors['bg'])
        
        # Rotate x-axis labels if needed
        if len(labels) > 5:
            plt.xticks(rotation=45, ha='right')

        plt.tight_layout()
        
        # Convert to base64
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')
        plt.close(fig)
        
        return img_base64

    def generate_pie_chart(
        self,
        data: list[dict[str, Any]],
        title: str = "",
        width: int = 600,
        height: int = 600,
    ) -> str:
        """Generate a pie chart and return base64-encoded image.

        Args:
            data: List of dicts with 'label' and 'value' keys
            title: Chart title
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            Base64-encoded PNG image string
        """
        fig, ax = plt.subplots(figsize=(width/100, height/100))
        
        labels = [item.get('label', '') for item in data]
        values = [item.get('value', 0) for item in data]
        colors = [
            item.get('color', self.colors['emerald'])
            for _ in values
        ]

        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=colors,
            autopct='%1.1f%%',
            startangle=90,
            textprops={'fontsize': 9},
        )

        ax.set_title(title, fontsize=12, fontweight='bold', pad=10)
        fig.patch.set_facecolor(self.colors['bg'])
        
        plt.tight_layout()
        
        # Convert to base64
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')
        plt.close(fig)
        
        return img_base64

    def generate_line_chart(
        self,
        data: list[dict[str, Any]],
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        width: int = 800,
        height: int = 400,
    ) -> str:
        """Generate a line chart and return base64-encoded image.

        Args:
            data: List of dicts with 'x' and 'y' keys
            title: Chart title
            xlabel: X-axis label
            ylabel: Y-axis label
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            Base64-encoded PNG image string
        """
        fig, ax = plt.subplots(figsize=(width/100, height/100))
        
        x_values = [item.get('x', i) for i, item in enumerate(data)]
        y_values = [item.get('y', 0) for item in data]

        ax.plot(x_values, y_values, color=self.colors['emerald'], linewidth=2)
        ax.fill_between(x_values, y_values, alpha=0.3, color=self.colors['emerald'])
        
        ax.set_title(title, fontsize=12, fontweight='bold', pad=10)
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_facecolor(self.colors['bg'])
        fig.patch.set_facecolor(self.colors['bg'])
        
        plt.tight_layout()
        
        # Convert to base64
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')
        plt.close(fig)
        
        return img_base64


# Singleton instance
_chart_generator: ChartGenerator | None = None


def get_chart_generator() -> ChartGenerator:
    """Get or create the singleton chart generator instance."""
    global _chart_generator
    if _chart_generator is None:
        _chart_generator = ChartGenerator()
    return _chart_generator
