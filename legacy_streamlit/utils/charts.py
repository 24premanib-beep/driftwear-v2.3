"""Tiny wrapper so every chart renders the same way."""
import streamlit as st

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}


def show(fig, key: str) -> None:
    st.plotly_chart(fig, config=PLOTLY_CONFIG, key=key)
